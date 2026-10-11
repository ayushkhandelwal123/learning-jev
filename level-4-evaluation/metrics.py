"""Pure evaluation logic. No API calls, no files: just numbers in, numbers out.

We compare what the policy DID (approve / remove / review) with what a human
moderator SHOULD have done (the gold label), and count the mistakes that
matter, because not all mistakes cost the same.
"""

from collections import Counter
from dataclasses import dataclass

from config import Thresholds
from policy import Action, Decision, Signals, decide
from store import GOLD_ACTIONS, LabeledPost

ACTION_TO_LABEL = {
    Action.AUTO_APPROVE: "approve",
    Action.AUTO_REMOVE: "remove",
    Action.HUMAN_REVIEW: "review",
}


# How much each kind of mistake HURTS (bigger = worse). Edit these to match your
# community. What you put here is what tune.py will optimise for.
# Not listed (e.g. sending a clean post to a human) = 0, because that mistake costs
# human time, which the automation rate already tracks.
ERROR_COSTS = {
    ("remove", "approve"): 10,   # a violation got published
    ("approve", "remove"): 5,    # a good post was removed
    ("review", "approve"): 3,    # a borderline post skipped the human
    ("review", "remove"): 3,     # a borderline post was removed without a human
}


@dataclass(frozen=True)
class Mistake:
    post: LabeledPost
    predicted: str
    decision: Decision


@dataclass(frozen=True)
class Report:
    n: int
    confusion: dict            # (gold, predicted) -> count
    harmful_approvals: int     # gold=remove but we published it  (worst)
    wrongful_removals: int     # gold=approve but we removed it   (also bad)
    automation_rate: float     # share decided without a human
    automated_accuracy: float  # of automated decisions, share that were right
    exact_accuracy: float      # all three labels, exact match
    cost: int                  # weighted mistakes, see ERROR_COSTS
    mistakes: tuple

    @property
    def serious_errors(self) -> int:
        return self.harmful_approvals + self.wrongful_removals


def evaluate(posts: list[LabeledPost], signals: dict, t: Thresholds = Thresholds()) -> Report:
    confusion: Counter = Counter()
    mistakes = []
    for post in posts:
        decision = decide(Signals(**signals[post.id]), t)
        predicted = ACTION_TO_LABEL[decision.action]
        confusion[(post.gold_action, predicted)] += 1
        if predicted != post.gold_action:
            mistakes.append(Mistake(post, predicted, decision))

    n = len(posts)
    automated = sum(c for (g, p), c in confusion.items() if p != "review")
    automated_right = sum(c for (g, p), c in confusion.items() if p != "review" and g == p)
    exact = sum(c for (g, p), c in confusion.items() if g == p)
    cost = sum(ERROR_COSTS.get(pair, 0) * count for pair, count in confusion.items())
    return Report(
        n=n,
        confusion=dict(confusion),
        harmful_approvals=confusion[("remove", "approve")],
        wrongful_removals=confusion[("approve", "remove")],
        automation_rate=automated / n if n else 0.0,
        automated_accuracy=automated_right / automated if automated else 1.0,
        exact_accuracy=exact / n if n else 0.0,
        cost=cost,
        mistakes=tuple(mistakes),
    )


def format_confusion(report: Report) -> str:
    """Rows = what a human says. Columns = what the policy did."""
    corner = "gold / predicted"
    header = f"{corner:<18}" + "".join(f"{p:>9}" for p in GOLD_ACTIONS)
    lines = [header]
    for g in GOLD_ACTIONS:
        cells = "".join(f"{report.confusion.get((g, p), 0):>9}" for p in GOLD_ACTIONS)
        lines.append(f"{g:<18}{cells}")
    return "\n".join(lines)


def post_type_accuracy(posts: list[LabeledPost], signals: dict) -> tuple[int, int]:
    """(correct, total) for the Choice question, on posts that have a gold type."""
    labelled = [p for p in posts if p.gold_post_type]
    correct = sum(1 for p in labelled if signals[p.id]["post_type"] == p.gold_post_type)
    return correct, len(labelled)


def mean_signals_by_gold(posts: list[LabeledPost], signals: dict) -> dict:
    """Average of each signal per gold label. A healthy signal separates the groups."""
    out = {}
    for label in GOLD_ACTIONS:
        group = [signals[p.id] for p in posts if p.gold_action == label]
        if group:
            out[label] = {k: sum(s[k] for s in group) / len(group)
                          for k in ("is_spam", "is_self_promotion",
                                    "shares_personal_info", "toxicity")}
    return out
