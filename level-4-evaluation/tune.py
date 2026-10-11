"""Step 3: search for better thresholds on the DEV posts, then check on TEST posts.

Usage (from the repository root):
    python level-4-evaluation/tune.py                 # all labelled posts
    python level-4-evaluation/tune.py --source hard   # tricky posts only

Why two splits? If you tune and score on the same posts, the thresholds just
memorise those posts. The test posts were never used for tuning, so they show
whether the improvement is real.
"""

import argparse
import itertools
import sys
from dataclasses import fields, replace

from config import Thresholds
from metrics import evaluate
from store import load_cache, load_labeled

# Values to try for each threshold. Add or remove values to widen the search.
GRID = {
    "spam_remove": [0.6, 0.7, 0.8, 0.9, 0.95],
    "personal_info_remove": [0.3, 0.4, 0.5, 0.7, 0.9],
    "toxicity_remove": [2.0, 2.5, 3.0, 3.5],
    "spam_approve_max": [0.05, 0.10, 0.15, 0.20, 0.30],
    "toxicity_approve_max": [0.5, 1.0, 1.5, 2.0],
}


def distance_from_defaults(t: Thresholds, default: Thresholds) -> float:
    """Tie-breaker: among equally good settings, prefer the least surprising one."""
    total = 0.0
    for name, values in GRID.items():
        span = max(values) - min(values)
        total += abs(getattr(t, name) - getattr(default, name)) / span
    return total


def describe(t: Thresholds) -> str:
    return ", ".join(f"{name}={getattr(t, name)}" for name in GRID)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="all",
                        help="all, starter or hard (the name after labeled_posts_)")
    args = parser.parse_args()

    signals = load_cache()
    posts = [p for p in load_labeled() if args.source in ("all", p.source)]
    missing = [p.id for p in posts if p.id not in signals]
    if missing:
        sys.exit(f"{len(missing)} posts have no cached Jev answers. Run collect.py first.")
    dev = [p for p in posts if p.split == "dev"]
    test = [p for p in posts if p.split == "test"]

    default = Thresholds()
    results = []
    for combo in itertools.product(*GRID.values()):
        t = replace(default, **dict(zip(GRID.keys(), combo)))
        r = evaluate(dev, signals, t)
        # Rank: lowest weighted mistake cost first, then most automation, then closest to
        # defaults. Cost weights live in metrics.ERROR_COSTS.
        key = (r.cost, -r.automation_rate, distance_from_defaults(t, default))
        results.append((key, t, r))
    results.sort(key=lambda x: x[0])

    best_key = results[0][0][:2]
    tied = sum(1 for key, _, _ in results if key[:2] == best_key)
    print(f"Searched {len(results)} threshold combinations on {len(dev)} dev posts.")
    print(f"{tied} of them tie for best (mistake cost={best_key[0]}, "
          f"automation={-best_key[1]:.0%}).")
    print("A big tie means a wide safe zone. A tie of 1 means a fragile result.")
    print("(serious = harmful approvals + wrongful removals only)\n")

    print("TOP 5 ON DEV")
    for key, t, r in results[:5]:
        print(f"  cost={r.cost} automation={r.automation_rate:.0%} | {describe(t)}")

    best = results[0][1]
    print("\nDEFAULTS vs TUNED")
    print(f"  {'':<10}{'split':<6}{'cost':>6}{'serious':>9}{'automation':>12}{'exact acc':>11}")
    for name, t in (("defaults", default), ("tuned", best)):
        for split_name, split in (("dev", dev), ("test", test)):
            r = evaluate(split, signals, t)
            print(f"  {name:<10}{split_name:<6}{r.cost:>6}{r.serious_errors:>9}"
                  f"{r.automation_rate:>12.0%}{r.exact_accuracy:>11.0%}")

    changed = {f.name: getattr(best, f.name) for f in fields(best)
               if getattr(best, f.name) != getattr(default, f.name)}
    print("\nTUNED CHANGES vs config.py defaults:")
    print("  " + (", ".join(f"{k}={v}" for k, v in changed.items()) or "none, defaults are already best"))
    print(f"\nCaution: with only {len(test)} test posts, one post changes a percentage a lot.")
    print("Treat tuned values as a hint to investigate, not a final answer.")


if __name__ == "__main__":
    main()
