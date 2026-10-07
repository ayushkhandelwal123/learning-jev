"""Test the decision policy with NO API calls.

Usage (from the repository root):
    python level-2-moderation-queue/test_policy.py
"""

from policy import Action, Signals, decide


def sig(**overrides) -> Signals:
    """A clearly safe post, with any fields you override."""
    base = dict(post_type="discussion", post_type_confidence=0.95, is_spam=0.02,
                is_self_promotion=0.02, shares_personal_info=0.01,
                toxicity=0.0, toxicity_confidence=1.0)
    base.update(overrides)
    return Signals(**base)


def check(name: str, signals: Signals, expected: Action) -> None:
    got = decide(signals).action
    status = "ok  " if got is expected else "FAIL"
    print(f"{status} {name}: expected {expected.value}, got {got.value}")
    assert got is expected, name


check("clean post is approved", sig(), Action.AUTO_APPROVE)
check("obvious spam is removed", sig(is_spam=0.97), Action.AUTO_REMOVE)
check("personal info is removed", sig(shares_personal_info=0.92), Action.AUTO_REMOVE)
check("threat is removed", sig(toxicity=3.6), Action.AUTO_REMOVE)
check("coin-flip spam goes to a human", sig(is_spam=0.52), Action.HUMAN_REVIEW)
check("sarcasm goes to a human", sig(toxicity=1.42, toxicity_confidence=0.65), Action.HUMAN_REVIEW)
check("promotion goes to a human", sig(is_self_promotion=0.9), Action.HUMAN_REVIEW)
check("high toxicity, low confidence goes to a human",
      sig(toxicity=3.4, toxicity_confidence=0.4), Action.HUMAN_REVIEW)
check("off-topic goes to a human", sig(post_type="off_topic"), Action.HUMAN_REVIEW)
print("\nAll policy tests passed.")
