"""Offline tests for the evaluation maths. No API keys or cache needed.

Usage (from the repository root):
    python level-4-evaluation/test_metrics.py
"""

from metrics import evaluate
from store import LabeledPost


def post(pid: str, gold: str) -> LabeledPost:
    return LabeledPost(pid, "dev", "text", gold, "")


def sig(**overrides) -> dict:
    base = dict(post_type="discussion", post_type_confidence=0.95, is_spam=0.02,
                is_self_promotion=0.02, shares_personal_info=0.01,
                toxicity=0.0, toxicity_confidence=1.0)
    base.update(overrides)
    return base


def expect(name: str, got, want) -> None:
    status = "ok  " if got == want else "FAIL"
    print(f"{status} {name}: expected {want}, got {got}")
    assert got == want, name


posts = [
    post("a", "approve"),   # clean -> approved (correct)
    post("b", "remove"),    # obvious spam -> removed (correct)
    post("c", "remove"),    # spam that Jev missed -> approved (HARMFUL)
    post("d", "approve"),   # good post Jev thinks is spam -> removed (WRONGFUL)
    post("e", "review"),    # borderline -> sent to a human (correct)
]
signals = {
    "a": sig(),
    "b": sig(is_spam=0.97),
    "c": sig(is_spam=0.02),
    "d": sig(is_spam=0.95),
    "e": sig(is_spam=0.5),
}

r = evaluate(posts, signals)
expect("harmful approvals", r.harmful_approvals, 1)
expect("wrongful removals", r.wrongful_removals, 1)
expect("serious errors", r.serious_errors, 2)
expect("automation rate", r.automation_rate, 0.8)          # 4 of 5 skipped a human
expect("automated accuracy", r.automated_accuracy, 0.5)    # 2 of 4 automated were right
expect("exact accuracy", r.exact_accuracy, 0.6)            # a, b, e match
expect("mistake count", len(r.mistakes), 2)
expect("weighted cost", r.cost, 15)                        # 10 (harmful) + 5 (wrongful)
expect("confusion cell", r.confusion[("remove", "approve")], 1)

# A borderline post that skips the human costs 3, and a post that only goes to a
# human unnecessarily costs 0.
r2 = evaluate([post("x", "review"), post("y", "approve")],
              {"x": sig(), "y": sig(is_spam=0.5)})
expect("missed review costs 3, needless review costs 0", r2.cost, 3)

print("\nAll metrics tests passed.")
