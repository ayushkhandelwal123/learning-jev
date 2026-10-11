"""Offline tests for the production machinery. No API keys, no network.

Usage (from the repository root):
    python level-5-production/test_resilience.py
"""

import asyncio
import tempfile
import time
from pathlib import Path

import httpx2
from typesafe_sdk import SystemOneResponse, TypeSafeAuthenticationError

from cache import CachedCaller, DiskCache, NullCache, make_key
from drafter import Draft, DraftError
from limiter import RateLimiter
from pipeline import Context, process_post
from policy import Action


def expect(name: str, got, want) -> None:
    status = "ok  " if got == want else "FAIL"
    print(f"{status} {name}: expected {want}, got {got}")
    assert got == want, name


def jev_response(spam: float = 0.02) -> SystemOneResponse:
    return SystemOneResponse.model_validate({
        "model": "fake-jev", "usage": {"input_tokens": 100, "output_tokens": 10},
        "answers": {
            "post_type": {"type": "choice", "choice": "discussion", "confidence": 0.9,
                          "probabilities": {"discussion": 0.9}},
            "is_spam": {"type": "noul", "noul": spam},
            "is_self_promotion": {"type": "noul", "noul": 0.02},
            "shares_personal_info": {"type": "noul", "noul": 0.01},
            "toxicity": {"type": "score", "score": 0.0, "confidence": 1.0,
                         "legend": {0: "a"}, "probabilities": {0: 1.0}},
        }})


class FakeClient:
    def __init__(self, spam: float = 0.02, error: Exception | None = None) -> None:
        self.calls, self.spam, self.error = 0, spam, error

    async def system_one(self, state, questions, **kw):
        self.calls += 1
        await asyncio.sleep(0.01)
        if self.error:
            raise self.error
        return jev_response(self.spam)


class FakeDrafter:
    model = "fake-llm"

    def __init__(self) -> None:
        self.calls = 0

    async def adraft(self, kind, text):
        self.calls += 1
        return Draft("Hi, thanks.\n- The Moderation Team", (), 10, 5)


class FlakyDrafter(FakeDrafter):
    """Fails on its first call (like a Groq rate limit), then works."""

    async def adraft(self, kind, text):
        self.calls += 1
        if self.calls == 1:
            raise DraftError("Groq rate limit reached (after retries).")
        return Draft("Hi, thanks.\n- The Moderation Team", (), 10, 5)


def make_ctx(client, cache, drafter=None, concurrency=5) -> Context:
    return Context(client=client, caller=CachedCaller(cache), jev_limiter=RateLimiter(0),
                   llm_limiter=RateLimiter(0), semaphore=asyncio.Semaphore(concurrency),
                   drafter=drafter, quiet=True, total=1)


async def tests() -> None:
    # --- keys -------------------------------------------------------------------
    expect("same parts give the same key", make_key("a", "b"), make_key("a", "b"))
    expect("different parts give a different key", make_key("a", "b") != make_key("a", "c"), True)
    expect("parts cannot blur together", make_key("ab", "c") != make_key("a", "bc"), True)

    # ignore_cleanup_errors: if an assertion fails, show THAT error, not a Windows
    # "file in use" error from cleaning up. (Caches are also closed explicitly below.)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "c.sqlite"

        # --- persistence ----------------------------------------------------------
        c1 = DiskCache(path)
        c1.set("signals", "k", {"x": 1})
        c1.close()
        c2 = DiskCache(path)
        expect("cache survives a restart", c2.get("signals", "k"), {"x": 1})
        expect("namespaces are separate", c2.get("drafts", "k"), None)
        c2.close()

        # --- rate limiter ---------------------------------------------------------
        limiter = RateLimiter(50)  # one start every 0.02s
        t0 = time.monotonic()
        await asyncio.gather(*(limiter.wait() for _ in range(6)))
        elapsed = time.monotonic() - t0
        expect("6 starts at 50/s take about 0.1s", 0.08 <= elapsed < 0.4, True)
        expect("the limiter counts the requests it started", limiter.count, 6)

        # --- single-flight: 10 identical requests make ONE call --------------------
        shared_cache = DiskCache(path)
        caller = CachedCaller(shared_cache)
        calls = 0

        async def slow_fetch():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return {"v": 1}

        outs = await asyncio.gather(*(caller.get("signals", "same", slow_fetch) for _ in range(10)))
        expect("10 concurrent identical requests make 1 call", calls, 1)
        expect("one owner, nine waiters",
               sorted(src for _, src in outs), ["api"] + ["deduped"] * 9)
        _, src = await caller.get("signals", "same", slow_fetch)
        expect("a later request is a cache hit", src, "cache")
        expect("still only 1 call in total", calls, 1)

        # --- failures are never cached ---------------------------------------------
        attempts = 0

        async def flaky():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("boom")
            return {"v": 2}

        try:
            await caller.get("signals", "flaky", flaky)
            raise AssertionError("expected an error")
        except RuntimeError:
            print("ok   a failed call raises to the caller")
        value, src = await caller.get("signals", "flaky", flaky)
        expect("a failure is not cached, so the retry works", (value, src), ({"v": 2}, "api"))

        # --- pipeline: success, then cache hit ---------------------------------------
        cache = DiskCache(Path(tmp) / "p.sqlite")
        client, drafter = FakeClient(spam=0.97), FakeDrafter()
        ctx = make_ctx(client, cache, drafter)
        r1 = await process_post("P1", "buy now!!!", ctx)
        expect("obvious spam is removed", r1.action, Action.AUTO_REMOVE)
        expect("first run used the API", (r1.signals_source, r1.draft_source), ("api", "api"))
        expect("a draft was written", r1.draft.startswith("Hi"), True)
        r2 = await process_post("P1b", "buy now!!!", make_ctx(client, cache, drafter))
        expect("second run is served from the cache", (r2.signals_source, r2.draft_source),
               ("cache", "cache"))
        expect("no extra Jev calls", client.calls, 1)
        expect("no extra LLM calls", drafter.calls, 1)

        # --- pipeline: dedupe inside one batch ----------------------------------------
        client2 = FakeClient()
        ctx2 = make_ctx(client2, NullCache())
        dedupe_cache = DiskCache(Path(tmp) / "d.sqlite")
        ctx2.caller = CachedCaller(dedupe_cache)
        batch = await asyncio.gather(*(process_post(f"D{i}", "same text", ctx2) for i in range(8)))
        expect("8 identical posts in a batch make 1 Jev call", client2.calls, 1)
        expect("all 8 got a decision", len(batch), 8)

        # --- fail-safe: an error is NOT an approval -------------------------------------
        ctx3 = make_ctx(FakeClient(error=RuntimeError("server on fire")), NullCache())
        r3 = await process_post("E1", "hello world", ctx3)
        expect("a failed post goes to a human", r3.action, Action.HUMAN_REVIEW)
        expect("the error is recorded", "server on fire" in r3.error, True)
        expect("a transient error does not abort the run", ctx3.fatal.is_set(), False)

        # --- fatal error: stop the run, skip the rest ------------------------------------
        auth_err = TypeSafeAuthenticationError(401, {}, httpx2.Headers())
        ctx4 = make_ctx(FakeClient(error=auth_err), NullCache(), concurrency=1)
        results = await asyncio.gather(*(process_post(f"F{i}", f"text {i}", ctx4) for i in range(5)))
        expect("a rejected API key aborts the run", ctx4.fatal.is_set(), True)
        expect("every post still ends in human review", {r.action for r in results},
               {Action.HUMAN_REVIEW})
        expect("later posts were skipped, not sent", ctx4.client.calls, 1)

        # --- a failed draft is not cached, so the next run retries it -------------------
        flaky_cache = DiskCache(Path(tmp) / "f.sqlite")
        flaky_client, flaky = FakeClient(spam=0.97), FlakyDrafter()
        first = await process_post("G1", "buy now!!!", make_ctx(flaky_client, flaky_cache, flaky))
        expect("run 1: the post is still decided", first.action, Action.AUTO_REMOVE)
        expect("run 1: no draft, and the failure is reported",
               (first.draft, first.warnings[0].startswith("draft failed")), ("", True))
        second = await process_post("G1b", "buy now!!!", make_ctx(flaky_client, flaky_cache, flaky))
        expect("run 2: signals come from the cache, the draft is retried",
               (second.signals_source, second.draft_source), ("cache", "api"))
        expect("run 2: the draft now exists", second.draft.startswith("Hi"), True)
        expect("Jev was only asked once", flaky_client.calls, 1)

        # Close every database BEFORE the temp folder is deleted. Windows refuses to
        # delete a file that is still open; Linux and macOS do not care.
        for open_cache in (shared_cache, cache, dedupe_cache, flaky_cache):
            open_cache.close()

    print("\nAll resilience tests passed.")


asyncio.run(tests())