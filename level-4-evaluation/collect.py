"""Step 1: ask Jev about every labelled post, once, and cache the answers.

Usage (from the repository root):
    python level-4-evaluation/collect.py            # only posts not yet cached
    python level-4-evaluation/collect.py --refresh  # ask about everything again
"""

import argparse
import os
import sys
from dataclasses import asdict

from dotenv import load_dotenv
from typesafe_sdk import (
    TypeSafeAPIError,
    TypeSafeAuthenticationError,
    TypeSafeClient,
    TypeSafeRateLimitError,
)

from policy import extract_signals
from questions import QUESTIONS
from store import CACHE_FILE, load_cache, load_labeled, save_cache

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="Ignore the cache and ask Jev about every post again.")
    args = parser.parse_args()

    if not os.getenv("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY not found. Check your .env file in the repo root.")

    posts = load_labeled()
    signals = {} if args.refresh else load_cache()
    todo = [p for p in posts if p.id not in signals]
    print(f"{len(posts)} labelled posts, {len(posts) - len(todo)} cached, "
          f"{len(todo)} to collect.")
    if not todo:
        print("Nothing to do. Use --refresh to collect again.")
        return

    tokens_in = tokens_out = 0
    try:
        with TypeSafeClient() as client:
            for post in todo:
                try:
                    response = client.system_one(state=post.text, questions=QUESTIONS)
                except TypeSafeAuthenticationError:
                    sys.exit("Authentication failed. Is TYPESAFE_API_KEY correct?")
                except TypeSafeRateLimitError:
                    print("Rate limited. Saving progress; run again to continue.")
                    break
                except TypeSafeAPIError as err:
                    print(f"{post.id}: API error, skipping ({err})")
                    continue
                signals[post.id] = asdict(extract_signals(response))
                tokens_in += response.usage.input_tokens
                tokens_out += response.usage.output_tokens
                print(f"  {post.id} done")
    finally:
        save_cache(signals)  # progress is kept even if something goes wrong

    print(f"\nSaved {len(signals)} posts to {CACHE_FILE}")
    print(f"Tokens used: {tokens_in} input, {tokens_out} output")


if __name__ == "__main__":
    main()
