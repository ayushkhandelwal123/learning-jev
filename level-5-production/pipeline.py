"""NEW in Level 5: the per-post pipeline, built to survive a messy real world.

   post -> [cache?] Jev signals -> policy -> routing -> [cache?] LLM draft

Design rules for production:
  1. One bad post must never stop the batch.
  2. FAILURES FAIL SAFE: a post we could not process goes to a human, never to
     "approve". An error is not a verdict.
  3. Fatal problems (a rejected API key) stop the whole run quickly instead of
     failing the same way 1,000 times.
  4. Retries are handled inside the SDKs (see main.py). This file never loops on errors.
"""

import asyncio
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field

from typesafe_sdk import TypeSafeAuthenticationError, TypeSafePermissionDeniedError

from cache import CachedCaller, make_key
from config import Thresholds
from drafter import DraftError, check_draft
from limiter import RateLimiter
from policy import Action, Signals, decide, extract_signals
from prompts import KIND_INSTRUCTIONS, SYSTEM_PROMPT
from questions import QUESTIONS
from routing import ReplyKind, choose_reply_kind


def _questions_fingerprint() -> str:
    payload = json.dumps({k: v.model_dump() for k, v in QUESTIONS.items()},
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


QUESTIONS_HASH = _questions_fingerprint()


def prompt_fingerprint(kind: ReplyKind) -> str:
    text = SYSTEM_PROMPT + KIND_INSTRUCTIONS[kind]
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class Context:
    """Everything a worker needs, bundled so it is easy to fake in tests."""

    client: object                 # AsyncTypeSafeClient (or a fake)
    caller: CachedCaller
    jev_limiter: RateLimiter
    llm_limiter: RateLimiter
    semaphore: asyncio.Semaphore   # max posts in flight at once
    thresholds: Thresholds = field(default_factory=Thresholds)
    drafter: object | None = None  # None means "do not draft" (dry run)
    pinned_model: str | None = None
    sdk_version: str = ""
    total: int = 0
    done: int = 0
    quiet: bool = False
    jev_models_seen: set = field(default_factory=set)
    tokens: Counter = field(default_factory=Counter)
    fatal: asyncio.Event = field(default_factory=asyncio.Event)
    fatal_message: str = ""


@dataclass(frozen=True)
class Result:
    post_id: str
    text: str
    action: Action
    reasons: tuple
    kind: ReplyKind
    draft: str = ""
    warnings: tuple = ()
    signals_source: str = ""   # "cache", "deduped", "api" or ""
    draft_source: str = ""
    error: str = ""
    seconds: float = 0.0


def signals_key(text: str, ctx: Context) -> str:
    # Thresholds are deliberately NOT part of the key: signals do not depend on them,
    # so tuning thresholds never forces new API calls.
    return make_key(text, QUESTIONS_HASH, ctx.pinned_model or "default-model", ctx.sdk_version)


def draft_key(kind: ReplyKind, text: str, llm_model: str) -> str:
    return make_key(kind.value, text, llm_model, prompt_fingerprint(kind))


async def _fetch_signals(text: str, ctx: Context) -> dict:
    await ctx.jev_limiter.wait()
    response = await ctx.client.system_one(state=text, questions=QUESTIONS)
    ctx.jev_models_seen.add(response.model)
    ctx.tokens["jev_in"] += response.usage.input_tokens
    ctx.tokens["jev_out"] += response.usage.output_tokens
    return {"signals": asdict(extract_signals(response)), "jev_model": response.model}


async def _fetch_draft(kind: ReplyKind, text: str, ctx: Context) -> dict:
    await ctx.llm_limiter.wait()
    draft = await ctx.drafter.adraft(kind, text)
    ctx.tokens["llm_in"] += draft.prompt_tokens
    ctx.tokens["llm_out"] += draft.completion_tokens
    return {"text": draft.text}


def _fail_safe(post_id: str, text: str, message: str, started: float, ctx: Context) -> Result:
    """A post we could not process goes to a human. It is never approved by default."""
    return _finish(Result(
        post_id=post_id, text=text, action=Action.HUMAN_REVIEW,
        reasons=("processing failed: a human must check this post",),
        kind=ReplyKind.NO_REPLY, error=message,
        seconds=time.perf_counter() - started,
    ), ctx)


def _finish(result: Result, ctx: Context) -> Result:
    ctx.done += 1
    if not ctx.quiet:
        flag = "  ERROR" if result.error else ""
        print(f"[{ctx.done:>3}/{ctx.total}] {result.post_id:<8} {result.action.value:<13} "
              f"jev:{result.signals_source or '-':<8} draft:{result.draft_source or '-':<8} "
              f"{result.seconds:5.1f}s{flag}")
    return result


async def process_post(post_id: str, text: str, ctx: Context) -> Result:
    started = time.perf_counter()
    if ctx.fatal.is_set():
        return _fail_safe(post_id, text, "skipped: the run was aborted", started, ctx)

    async with ctx.semaphore:
        # Measure from here, not from when the post was created. Otherwise every post
        # would include the time it spent queueing for a free worker slot.
        started = time.perf_counter()
        if ctx.fatal.is_set():  # the abort may have happened while we waited
            return _fail_safe(post_id, text, "skipped: the run was aborted", started, ctx)

        # ---- 1. Jev signals (cache, or one call shared by identical posts) -----
        try:
            entry, signals_source = await ctx.caller.get(
                "signals", signals_key(text, ctx), lambda: _fetch_signals(text, ctx))
        except (TypeSafeAuthenticationError, TypeSafePermissionDeniedError) as err:
            ctx.fatal.set()  # no point continuing: every call would fail the same way
            ctx.fatal_message = f"TypeSafe rejected the request ({type(err).__name__})."
            return _fail_safe(post_id, text, ctx.fatal_message, started, ctx)
        except Exception as err:  # retries inside the SDK are already exhausted
            return _fail_safe(post_id, text, f"Jev call failed: {type(err).__name__}: {err}",
                              started, ctx)

        # ---- 2. Decide and route (pure functions, instant, no I/O) ------------
        signals = Signals(**entry["signals"])
        decision = decide(signals, ctx.thresholds)
        kind = choose_reply_kind(signals, decision, ctx.thresholds)

        # ---- 3. Draft a message if one is needed ------------------------------
        draft, warnings, draft_source = "", (), ""
        if kind is not ReplyKind.NO_REPLY and ctx.drafter is not None:
            try:
                value, draft_source = await ctx.caller.get(
                    "drafts", draft_key(kind, text, ctx.drafter.model),
                    lambda: _fetch_draft(kind, text, ctx))
                draft = value["text"]
                # Guardrail runs on every read, so improving it also protects old drafts.
                warnings = check_draft(draft)
            except DraftError as err:
                warnings = (f"draft failed: {err}",)
            except Exception as err:
                warnings = (f"draft failed: {type(err).__name__}: {err}",)

        return _finish(Result(
            post_id=post_id, text=text, action=decision.action, reasons=decision.reasons,
            kind=kind, draft=draft, warnings=tuple(warnings),
            signals_source=signals_source, draft_source=draft_source,
            seconds=time.perf_counter() - started,
        ), ctx)