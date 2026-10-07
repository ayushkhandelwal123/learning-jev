"""Level 2: Jev signals -> thresholds -> approve / remove / human review.

Usage (from the repository root):
    python level-2-moderation-queue/main.py
"""

import csv
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from typesafe_sdk import (
    TypeSafeAPIError,
    TypeSafeAuthenticationError,
    TypeSafeClient,
    TypeSafeRateLimitError,
)

from policy import Action, decide, extract_signals
from questions import QUESTIONS
from sample_posts import POSTS

load_dotenv()

OUTPUT_DIR = Path(__file__).parent / "output"  # git-ignored


def main() -> None:
    if not os.getenv("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY not found. Check your .env file in the repo root.")

    rows = []
    tokens_in = tokens_out = 0

    with TypeSafeClient() as client:
        for post_id, text in POSTS:
            try:
                response = client.system_one(state=text, questions=QUESTIONS)
            except TypeSafeAuthenticationError:
                sys.exit("Authentication failed. Is TYPESAFE_API_KEY correct?")
            except TypeSafeRateLimitError:
                sys.exit("Rate limited. Wait a bit and run again.")
            except TypeSafeAPIError as err:
                print(f"{post_id}: API error, skipping ({err})")
                continue

            signals = extract_signals(response)  # Jev -> plain numbers
            decision = decide(signals)           # numbers -> action
            tokens_in += response.usage.input_tokens
            tokens_out += response.usage.output_tokens

            rows.append((post_id, text, signals, decision))
            print(f"{post_id}  {decision.action.value:<13} "
                  f"spam={signals.is_spam:.2f} promo={signals.is_self_promotion:.2f} "
                  f"pii={signals.shares_personal_info:.2f} tox={signals.toxicity:.2f}")

    # ---- Summary ---------------------------------------------------------
    counts = Counter(r[3].action for r in rows)
    total = len(rows) or 1
    print("\n" + "=" * 70)
    print("SUMMARY")
    for action in Action:
        n = counts.get(action, 0)
        print(f"  {action.value:<13} {n:>3}  ({n / total:.0%})")

    # ---- Human review queue, most urgent first -----------------------------
    queue = sorted((r for r in rows if r[3].action is Action.HUMAN_REVIEW),
                   key=lambda r: r[3].priority, reverse=True)
    print("\nHUMAN REVIEW QUEUE (most urgent first)")
    if not queue:
        print("  (empty)")
    for post_id, text, _signals, decision in queue:
        print(f"  [{decision.priority:.2f}] {post_id}: {text[:55]}")
        for reason in decision.reasons:
            print(f"         - {reason}")

    # ---- Save every decision to CSV ----------------------------------------
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_file = OUTPUT_DIR / "decisions.csv"
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["post_id", "action", "priority", "post_type", "is_spam",
                         "is_self_promotion", "shares_personal_info", "toxicity",
                         "reasons", "text"])
        for post_id, text, s, d in rows:
            writer.writerow([post_id, d.action.value, f"{d.priority:.2f}", s.post_type,
                             f"{s.is_spam:.2f}", f"{s.is_self_promotion:.2f}",
                             f"{s.shares_personal_info:.2f}", f"{s.toxicity:.2f}",
                             " | ".join(d.reasons), text])

    print(f"\nSaved {len(rows)} decisions to {out_file}")
    print(f"Tokens used: {tokens_in} input, {tokens_out} output")


if __name__ == "__main__":
    main()
