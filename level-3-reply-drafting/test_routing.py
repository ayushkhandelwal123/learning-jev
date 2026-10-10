"""Offline tests for routing and the draft guardrail. No API keys needed.

Usage (from the repository root):
    python level-3-reply-drafting/test_routing.py
"""

from drafter import check_draft
from policy import Signals, decide
from routing import ReplyKind, choose_reply_kind


def sig(**overrides) -> Signals:
    base = dict(post_type="discussion", post_type_confidence=0.95, is_spam=0.02,
                is_self_promotion=0.02, shares_personal_info=0.01,
                toxicity=0.0, toxicity_confidence=1.0)
    base.update(overrides)
    return Signals(**base)


def route(**overrides) -> ReplyKind:
    s = sig(**overrides)
    return choose_reply_kind(s, decide(s))


def expect(name: str, got, want) -> None:
    status = "ok  " if got == want else "FAIL"
    print(f"{status} {name}: expected {getattr(want, 'value', want)}, "
          f"got {getattr(got, 'value', got)}")
    assert got == want, name


# --- routing ---------------------------------------------------------------
expect("clean post needs no reply", route(), ReplyKind.NO_REPLY)
expect("showcase with self-promotion is approved (the Level 2 fix)",
       route(post_type="showcase", is_self_promotion=0.93), ReplyKind.NO_REPLY)
expect("spam removal", route(is_spam=0.97), ReplyKind.REMOVAL_SPAM)
expect("personal info removal", route(shares_personal_info=0.92), ReplyKind.REMOVAL_PERSONAL_INFO)
expect("abuse removal", route(toxicity=3.6), ReplyKind.REMOVAL_ABUSE)
expect("privacy beats spam when both fire",
       route(is_spam=0.95, shares_personal_info=0.9), ReplyKind.REMOVAL_PERSONAL_INFO)
expect("sarcasm gets a tone reminder",
       route(toxicity=1.44, toxicity_confidence=0.65), ReplyKind.REVIEW_TONE)
expect("promotion gets the promotion message",
       route(post_type="promotion", is_self_promotion=0.99, is_spam=0.2), ReplyKind.REVIEW_PROMOTION)
expect("off-topic gets a redirect", route(post_type="off_topic"), ReplyKind.REVIEW_OFFTOPIC)
expect("unclear review case gets no draft", route(is_spam=0.5), ReplyKind.NO_REPLY)

# --- guardrail on LLM output --------------------------------------------------
good = "Hi, thanks for posting. Please keep feedback constructive.\n- The Moderation Team"
expect("good draft has no warnings", check_draft(good), ())
expect("email in draft is flagged",
       len(check_draft("Hi, contact john.doe@example.com for details.")) >= 1, True)
expect("phone in draft is flagged",
       len(check_draft("Hi, call 555-0142 for details.")) >= 1, True)
expect("wrong format is flagged", len(check_draft("Sure! Here is a draft:")) >= 1, True)

print("\nAll routing and guardrail tests passed.")
