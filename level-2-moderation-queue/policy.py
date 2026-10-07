"""The decision policy: turns Jev's numbers into an action.

This file NEVER calls Jev. It is a pure function of numbers, so you can
test it instantly, for free, and change the rules without touching the API.

Rule order matters (first match wins):
  1. AUTO_REMOVE  if any clear-violation rule fires
  2. AUTO_APPROVE if every "clearly safe" check passes
  3. HUMAN_REVIEW for everything else (the uncertain middle)
"""

from dataclasses import dataclass
from enum import Enum

from config import Thresholds


class Action(str, Enum):
    AUTO_APPROVE = "auto_approve"
    AUTO_REMOVE = "auto_remove"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class Signals:
    """The numbers we pull out of a Jev response."""

    post_type: str
    post_type_confidence: float
    is_spam: float
    is_self_promotion: float
    shares_personal_info: float
    toxicity: float
    toxicity_confidence: float


@dataclass(frozen=True)
class Decision:
    action: Action
    reasons: tuple[str, ...]
    priority: float  # 0 to 1; higher = look at it sooner


def extract_signals(response) -> Signals:
    """Pull plain numbers out of a Jev response object."""
    post_type = response.choices["post_type"]
    toxicity = response.scores["toxicity"]
    return Signals(
        post_type=post_type.choice,
        post_type_confidence=post_type.confidence,
        is_spam=response.nouls["is_spam"].noul,
        is_self_promotion=response.nouls["is_self_promotion"].noul,
        shares_personal_info=response.nouls["shares_personal_info"].noul,
        toxicity=toxicity.score,
        toxicity_confidence=toxicity.confidence,
    )


def decide(s: Signals, t: Thresholds = Thresholds()) -> Decision:
    # How urgent is a human look? Worst signal wins; toxicity scaled to 0-1.
    priority = max(s.is_spam, s.shares_personal_info, s.toxicity / 4)

    # ---- 1. AUTO-REMOVE: any one clear violation -------------------------
    remove = []
    if s.is_spam >= t.spam_remove:
        remove.append(f"spam {s.is_spam:.2f} >= {t.spam_remove}")
    if s.shares_personal_info >= t.personal_info_remove:
        remove.append(f"personal info {s.shares_personal_info:.2f} >= {t.personal_info_remove}")
    if s.toxicity >= t.toxicity_remove and s.toxicity_confidence >= t.toxicity_min_confidence:
        remove.append(f"toxicity {s.toxicity:.2f} >= {t.toxicity_remove}")
    if remove:
        return Decision(Action.AUTO_REMOVE, tuple(remove), priority)

    # ---- 2. AUTO-APPROVE: every check must pass --------------------------
    # Each entry: (check passed?, message shown if it FAILED)
    checks = [
        (s.is_spam <= t.spam_approve_max,
         f"spam {s.is_spam:.2f} above {t.spam_approve_max}"),
        (s.is_self_promotion <= t.self_promotion_approve_max,
         f"self-promotion {s.is_self_promotion:.2f} above {t.self_promotion_approve_max}"),
        (s.shares_personal_info <= t.personal_info_approve_max,
         f"personal info {s.shares_personal_info:.2f} above {t.personal_info_approve_max}"),
        (s.toxicity <= t.toxicity_approve_max,
         f"toxicity {s.toxicity:.2f} above {t.toxicity_approve_max}"),
        (s.toxicity_confidence >= t.toxicity_min_confidence,
         f"toxicity confidence {s.toxicity_confidence:.2f} below {t.toxicity_min_confidence}"),
        # post_type is a Choice, so it can drive a rule too, not just numbers.
        (s.post_type != "off_topic", "post looks off-topic for this community"),
    ]
    failed = tuple(msg for ok, msg in checks if not ok)
    if not failed:
        return Decision(Action.AUTO_APPROVE, ("all checks passed",), priority)

    # ---- 3. HUMAN REVIEW: the uncertain middle ---------------------------
    return Decision(Action.HUMAN_REVIEW, failed, priority)
