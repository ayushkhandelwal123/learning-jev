"""Level 5: the whole pipeline, run at volume.

Adds to Level 3: async concurrency, rate limiting, SDK retries, a persistent cache
with single-flight de-duplication, fail-safe error handling, and a run manifest.

Usage (from the repository root):
    python level-5-production/main.py                    # all 60 posts
    python level-5-production/main.py --dry-run          # Jev only, no LLM drafts
    python level-5-production/main.py --limit 10 --copies 3
    python level-5-production/main.py --concurrency 10 --rps 10
    python level-5-production/main.py --no-cache         # force fresh calls
"""

import argparse
import asyncio
import csv
import json
import os
import platform
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from dotenv import load_dotenv
from typesafe_sdk import (
    AsyncTypeSafeClient,
    RetryPolicy,
    TypeSafeAPIError,
    TypeSafeAuthenticationError,
)

from cache import CachedCaller, DiskCache, NullCache
from config import Thresholds
from drafter import DraftError, Drafter
from limiter import RateLimiter
from pipeline import QUESTIONS_HASH, Context, Result, process_post
from policy import Action

load_dotenv()

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"  # git-ignored


def load_posts(limit: int | None, copies: int) -> list[tuple[str, str]]:
    with open(HERE / "posts.csv", newline="", encoding="utf-8") as f:
        posts = [(row["id"], row["text"]) for row in csv.DictReader(f)]
    if limit:
        posts = posts[:limit]
    # --copies repeats every post. The repeats have identical text, so they are
    # answered from the cache or a shared in-flight call instead of new API calls.
    return [(pid if c == 0 else f"{pid}#{c + 1}", text)
            for c in range(copies) for pid, text in posts]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--limit", type=int, help="Only process the first N posts.")
    p.add_argument("--copies", type=int, default=1, help="Repeat every post N times.")
    p.add_argument("--concurrency", type=int, default=5, help="Max posts in flight at once.")
    p.add_argument("--rps", type=float, default=5.0, help="Max Jev requests started per second.")
    p.add_argument("--llm-rps", type=float, default=1.0,
                   help="Max Groq requests started per second (check your Groq limits).")
    p.add_argument("--dry-run", action="store_true", help="Skip the LLM drafting step.")
    p.add_argument("--no-cache", action="store_true", help="Ignore and do not write the cache.")
    return p.parse_args()


async def run(args: argparse.Namespace, drafter: Drafter | None) -> int:
    posts = load_posts(args.limit, args.copies)
    cache = NullCache() if args.no_cache else DiskCache(OUTPUT_DIR / "cache.sqlite")
    caller = CachedCaller(cache, dedupe=not args.no_cache)

    pinned_model = os.getenv("TYPESAFE_MODEL") or None  # optional: pin the Jev model
    # The SDK retries rate limits (429), server errors (5xx), timeouts and dropped
    # connections with exponential backoff and jitter, and honours Retry-After headers.
    retry = RetryPolicy(max_retries=4, backoff_initial=1.0, backoff_max=20.0, timeout=90.0)

    started_at = datetime.now(timezone.utc)
    async with AsyncTypeSafeClient(model=pinned_model, retry=retry, timeout=30.0) as client:
        try:
            available = [m.name for m in (await client.models.list()).models]
        except TypeSafeAuthenticationError:
            print("TypeSafe authentication failed. Check TYPESAFE_API_KEY in .env.")
            return 1
        print(f"Jev models available: {', '.join(available) or '(none listed)'}")
        if pinned_model and pinned_model not in available:
            print(f"TYPESAFE_MODEL='{pinned_model}' is not available. Choose one of the above.")
            return 1
        print(f"Using Jev model: {pinned_model or 'the SDK default (not pinned)'}")
        if drafter:
            print(f"Drafting with Groq model: {drafter.model}")
        print(f"{len(posts)} posts | concurrency {args.concurrency} | "
              f"Jev {args.rps}/s | LLM {args.llm_rps}/s | "
              f"cache {'off' if args.no_cache else 'on'}\n")

        ctx = Context(
            client=client, caller=caller,
            jev_limiter=RateLimiter(args.rps), llm_limiter=RateLimiter(args.llm_rps),
            semaphore=asyncio.Semaphore(args.concurrency),
            thresholds=Thresholds(), drafter=drafter,
            pinned_model=pinned_model, sdk_version=version("typesafe-sdk"),
            total=len(posts),
        )
        t0 = time.perf_counter()
        results: list[Result] = await asyncio.gather(
            *(process_post(pid, text, ctx) for pid, text in posts))
        wall = time.perf_counter() - t0

    cache_entries = {ns: cache.count(ns) for ns in ("signals", "drafts")}
    cache.close()

    # ---- Summary ---------------------------------------------------------------
    actions = Counter(r.action for r in results)
    errors = [r for r in results if r.error]
    api_latencies = [r.seconds for r in results if r.signals_source == "api"]
    print("\n" + "=" * 72)
    print("SUMMARY")
    for action in Action:
        print(f"  {action.value:<13} {actions.get(action, 0)}")
    print(f"  errors (sent to human review as a fail-safe): {len(errors)}")
    print(f"  drafts written: {sum(1 for r in results if r.draft)}   "
          f"with warnings: {sum(1 for r in results if r.warnings)}")
    failed_drafts = [(r.post_id, w) for r in results for w in r.warnings
                     if w.startswith("draft failed")]
    print(f"  drafts that FAILED (not cached, so the next run retries them): {len(failed_drafts)}")
    for post_id, warning in failed_drafts[:3]:
        print(f"    {post_id}: {warning}")
    print("\nWHERE ANSWERS CAME FROM")
    for (namespace, source), n in sorted(caller.sources.items()):
        print(f"  {namespace:<8} {source:<8} {n}")
    print(f"\nTIMING: {wall:.1f}s total, {len(results) / wall:.1f} posts/s")
    if api_latencies:
        print(f"  Jev-backed posts: median {percentile(api_latencies, 0.5):.1f}s, "
              f"p95 {percentile(api_latencies, 0.95):.1f}s")
    print("  (per-post times exclude time spent queueing for a worker slot)")
    # The fastest this run could possibly finish, set by the rate limiters alone.
    for label, limiter, rps in (("Jev", ctx.jev_limiter, args.rps),
                                ("LLM", ctx.llm_limiter, args.llm_rps)):
        if rps > 0 and limiter.count > 1:
            print(f"  {label} rate-limit floor: {limiter.count} requests at {rps}/s "
                  f"cannot finish in under {(limiter.count - 1) / rps:.0f}s")
    print(f"\nTOKENS (only for real API calls; cached answers cost nothing): "
          f"{dict(ctx.tokens) or 'none'}")
    for r in errors[:5]:
        print(f"  ERROR {r.post_id}: {r.error}")
    if ctx.fatal.is_set():
        print(f"\nRUN ABORTED: {ctx.fatal_message}")

    # ---- Save results and a manifest so the run can be reproduced -----------------
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["post_id", "action", "reply_kind", "reasons", "draft", "warnings",
                    "signals_source", "draft_source", "seconds", "error", "text"])
        for r in results:
            w.writerow([r.post_id, r.action.value, r.kind.value, " | ".join(r.reasons), r.draft,
                        " | ".join(r.warnings), r.signals_source, r.draft_source,
                        f"{r.seconds:.2f}", r.error, r.text])
    manifest = {
        "started_at": started_at.isoformat(),
        "python": platform.python_version(),
        "packages": {n: version(n) for n in ("typesafe-sdk", "langchain-groq", "groq", "python-dotenv")},
        "jev_model_requested": pinned_model or "default (not pinned)",
        "jev_models_seen_in_new_calls": sorted(ctx.jev_models_seen),
        "groq_model": drafter.model if drafter else None,
        "questions_hash": QUESTIONS_HASH,
        "thresholds": asdict(Thresholds()),
        "settings": {k: v for k, v in vars(args).items()},
        "posts": len(results), "errors": len(errors), "wall_seconds": round(wall, 2),
        "answer_sources": {f"{ns}:{src}": n for (ns, src), n in sorted(caller.sources.items())},
        "cache_entries": cache_entries,
    }
    (OUTPUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nSaved results.csv and run_manifest.json to {OUTPUT_DIR}")
    return 1 if ctx.fatal.is_set() else 0


def main() -> None:
    args = parse_args()
    if args.concurrency < 1 or args.copies < 1:
        sys.exit("--concurrency and --copies must be at least 1.")
    if not os.getenv("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY not found. Check your .env file in the repo root.")

    drafter = None
    if not args.dry_run:
        if not os.getenv("GROQ_API_KEY"):
            sys.exit("GROQ_API_KEY not found. Add it to .env, or use --dry-run.")
        drafter = Drafter()
        try:
            drafter.verify_model()
        except DraftError as err:
            sys.exit(str(err))

    sys.exit(asyncio.run(run(args, drafter)))


if __name__ == "__main__":
    main()