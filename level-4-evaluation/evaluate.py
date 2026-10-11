"""Step 2: score the CURRENT thresholds against your gold labels. Offline and free.

Usage (from the repository root):
    python level-4-evaluation/evaluate.py              # all labelled posts
    python level-4-evaluation/evaluate.py --split test # only the held-out posts
    python level-4-evaluation/evaluate.py --source hard   # only the tricky posts
    python level-4-evaluation/evaluate.py --source starter
"""

import argparse
import sys

from config import Thresholds
from metrics import (
    evaluate,
    format_confusion,
    mean_signals_by_gold,
    post_type_accuracy,
)
from store import load_cache, load_labeled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument("--source", default="all",
                        help="all, starter or hard (the name after labeled_posts_)")
    args = parser.parse_args()

    signals = load_cache()
    posts = [p for p in load_labeled()
             if args.split in ("all", p.split) and args.source in ("all", p.source)]
    if not posts:
        sys.exit("No posts match that --split / --source combination.")
    missing = [p.id for p in posts if p.id not in signals]
    if missing:
        sys.exit(f"{len(missing)} posts have no cached Jev answers. Run collect.py first.")

    report = evaluate(posts, signals, Thresholds())
    print(f"EVALUATION on '{args.split}' split, '{args.source}' source: {report.n} posts\n")
    print(format_confusion(report))

    print("\nMETRICS")
    print(f"  harmful approvals (violation published) : {report.harmful_approvals}")
    print(f"  wrongful removals (good post removed)   : {report.wrongful_removals}")
    print(f"  automation rate (no human needed)       : {report.automation_rate:.0%}")
    print(f"  accuracy of automated decisions         : {report.automated_accuracy:.0%}")
    print(f"  exact agreement with gold labels        : {report.exact_accuracy:.0%}")
    print(f"  weighted mistake cost (lower is better) : {report.cost}")
    correct, total = post_type_accuracy(posts, signals)
    print(f"  post_type (Choice) accuracy             : {correct}/{total}")

    for p in posts:
        if p.gold_post_type and signals[p.id]["post_type"] != p.gold_post_type:
            print(f"    post_type miss {p.id}: gold={p.gold_post_type}, "
                  f"jev={signals[p.id]['post_type']}: {p.text[:50]}")

    print("\nMEAN SIGNAL BY GOLD LABEL (good signals separate the rows)")
    print(f"  {'gold':<9}{'spam':>7}{'promo':>8}{'pii':>7}{'toxicity':>10}")
    for label, m in mean_signals_by_gold(posts, signals).items():
        print(f"  {label:<9}{m['is_spam']:>7.2f}{m['is_self_promotion']:>8.2f}"
              f"{m['shares_personal_info']:>7.2f}{m['toxicity']:>10.2f}")

    print("\nMISTAKES")
    if not report.mistakes:
        print("  none")
    for m in report.mistakes:
        print(f"  {m.post.id} gold={m.post.gold_action} predicted={m.predicted}: "
              f"{m.post.text[:60]}")
        print(f"      {'; '.join(m.decision.reasons)}")


if __name__ == "__main__":
    main()
