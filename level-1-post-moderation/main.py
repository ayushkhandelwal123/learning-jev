"""Level 1: run every sample post through Jev and print the raw answers.

Usage (from the repository root):
    python level-1-post-moderation/main.py
"""

import os
import sys

from dotenv import load_dotenv
from typesafe_sdk import (
    TypeSafeAPIError,
    TypeSafeAuthenticationError,
    TypeSafeClient,
    TypeSafeRateLimitError,
)

from questions import QUESTIONS
from sample_posts import POSTS

# Looks for a .env file in this folder, then in each parent folder,
# so the .env in the repository root is found automatically.
load_dotenv()


def show(post_id: str, text: str, response) -> None:
    """Print every answer in a readable way, including the raw numbers."""
    post_type = response.choices["post_type"]
    spam = response.nouls["is_spam"]
    pii = response.nouls["shares_personal_info"]
    tox = response.scores["toxicity"]

    # A Score is fractional. The legend maps level numbers to your criteria text.
    nearest = round(tox.score)
    label = tox.legend.get(nearest, "?")

    print("=" * 78)
    print(f"{post_id}: {text}")
    print("-" * 78)
    print(f"post_type  : {post_type.choice} (confidence {post_type.confidence:.2f})")
    ranked = sorted(post_type.probabilities.items(), key=lambda kv: kv[1], reverse=True)
    print("             " + ", ".join(f"{name}={p:.2f}" for name, p in ranked))
    print(f"is_spam    : {spam.noul:.2f}")
    print(f"personal   : {pii.noul:.2f}")
    print(f"toxicity   : {tox.score:.2f} of 4 (nearest level {nearest}: {label}), "
          f"confidence {tox.confidence:.2f}")


def main() -> None:
    if not os.getenv("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY not found. Check your .env file in the repo root.")

    total_in = total_out = 0
    # The with-block closes the underlying HTTP connection for us.
    with TypeSafeClient() as client:
        for post_id, text in POSTS:
            try:
                # ONE request carries the post plus all four questions.
                response = client.system_one(state=text, questions=QUESTIONS)
            except TypeSafeAuthenticationError:
                sys.exit("Authentication failed. Is TYPESAFE_API_KEY correct?")
            except TypeSafeRateLimitError:
                sys.exit("Rate limited. Wait a bit and run again.")
            except TypeSafeAPIError as err:
                print(f"{post_id}: API error, skipping ({err})")
                continue

            show(post_id, text, response)
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

    print("=" * 78)
    print(f"Tokens used: {total_in} input, {total_out} output")


if __name__ == "__main__":
    main()
