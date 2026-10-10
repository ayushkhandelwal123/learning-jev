"""Level 3: Jev decides, the LLM writes.

Pipeline per post:
  Jev (signals) -> policy (action) -> routing (message kind) -> Groq LLM (draft)

Usage (from the repository root):
    python level-3-reply-drafting/main.py              # full run
    python level-3-reply-drafting/main.py --dry-run    # skip the LLM, show routing only
"""

import argparse
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

from drafter import DraftError, Drafter
from policy import Action, decide, extract_signals
from questions import QUESTIONS
from routing import ReplyKind, choose_reply_kind
from sample_posts import POSTS

load_dotenv()

OUTPUT_DIR = Path(__file__).parent / "output"  # git-ignored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip the LLM. Show Jev decisions and message routing only.")
    args = parser.parse_args()

    if not os.getenv("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY not found. Check your .env file in the repo root.")
    if not args.dry_run and not os.getenv("GROQ_API_KEY"):
        sys.exit("GROQ_API_KEY not found. Add it to .env, or use --dry-run.")

    drafter = None
    if not args.dry_run:
        drafter = Drafter()
        try:
            drafter.verify_model()
        except DraftError as err:
            sys.exit(str(err))
        print(f"Drafting with Groq model: {drafter.model}\n")

    rows = []
    jev_in = jev_out = llm_in = llm_out = 0

    with TypeSafeClient() as client:
        for post_id, text in POSTS:
            # ---- Step 1: Jev reads the post ---------------------------------
            try:
                response = client.system_one(state=text, questions=QUESTIONS)
            except TypeSafeAuthenticationError:
                sys.exit("TypeSafe authentication failed. Is TYPESAFE_API_KEY correct?")
            except TypeSafeRateLimitError:
                sys.exit("TypeSafe rate limit reached. Wait a bit and run again.")
            except TypeSafeAPIError as err:
                print(f"{post_id}: Jev error, skipping ({err})")
                continue
            jev_in += response.usage.input_tokens
            jev_out += response.usage.output_tokens

            # ---- Step 2 and 3: numbers -> action -> message kind -------------
            signals = extract_signals(response)
            decision = decide(signals)
            kind = choose_reply_kind(signals, decision)

            # ---- Step 4: the LLM writes (only when a message is needed) ------
            draft_text, warnings = "", ()
            if kind is not ReplyKind.NO_REPLY and drafter is not None:
                try:
                    draft = drafter.draft(kind, text)
                    draft_text, warnings = draft.text, draft.warnings
                    llm_in += draft.prompt_tokens
                    llm_out += draft.completion_tokens
                except DraftError as err:
                    warnings = (f"draft failed: {err}",)

            rows.append((post_id, text, decision, kind, draft_text, warnings))

            print("=" * 74)
            print(f"{post_id}: {text[:68]}")
            print(f"  action : {decision.action.value}")
            print(f"  reasons: {'; '.join(decision.reasons)}")
            print(f"  message: {kind.value}")
            if draft_text:
                print("  DRAFT  :")
                for line in draft_text.splitlines():
                    print(f"    {line}")
            for w in warnings:
                print(f"  WARNING: {w}")

    # ---- Summary -----------------------------------------------------------
    counts = Counter(r[2].action for r in rows)
    drafted = sum(1 for r in rows if r[4])
    flagged = sum(1 for r in rows if r[5])
    print("\n" + "=" * 74)
    print("SUMMARY")
    for action in Action:
        print(f"  {action.value:<13} {counts.get(action, 0)}")
    print(f"  drafts written: {drafted}   drafts with warnings: {flagged}")
    print(f"  Jev tokens: {jev_in} in / {jev_out} out")
    if not args.dry_run:
        print(f"  LLM tokens: {llm_in} in / {llm_out} out")

    # ---- Save everything to CSV --------------------------------------------
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_file = OUTPUT_DIR / "drafts.csv"
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["post_id", "action", "reply_kind", "reasons", "draft",
                         "warnings", "post_text"])
        for post_id, text, d, kind, draft_text, warnings in rows:
            writer.writerow([post_id, d.action.value, kind.value, " | ".join(d.reasons),
                             draft_text, " | ".join(warnings), text])
    print(f"\nSaved {len(rows)} rows to {out_file}")


if __name__ == "__main__":
    main()
