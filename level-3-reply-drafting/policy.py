"""The decision policy (from Level 2, with ONE fix).

Fix: self-promotion is only a concern when the post is actually a promotion.
In Level 2, an honest showcase ("I launched my CLI tool!") scored 0.93 on
is_self_promotion and was sent to a human for no good reason.

This file never calls Jev. Rule order (first match wins):
  1. AUTO_REMOVE  2. AUTO_APPROVE  3. HUMAN_REVIEW
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
    checks = [
        (s.is_spam <= t.spam_approve_max,
         f"spam {s.is_spam:.2f} above {t.spam_approve_max}"),
        # FIX: only worry about self-promotion on posts that ARE promotions.
        (s.post_type != "promotion" or s.is_self_promotion <= t.self_promotion_approve_max,
         f"self-promotion {s.is_self_promotion:.2f} above {t.self_promotion_approve_max}"),
        (s.shares_personal_info <= t.personal_info_approve_max,
         f"personal info {s.shares_personal_info:.2f} above {t.personal_info_approve_max}"),
        (s.toxicity <= t.toxicity_approve_max,
         f"toxicity {s.toxicity:.2f} above {t.toxicity_approve_max}"),
        (s.toxicity_confidence >= t.toxicity_min_confidence,
         f"toxicity confidence {s.toxicity_confidence:.2f} below {t.toxicity_min_confidence}"),
        (s.post_type != "off_topic", "post looks off-topic for this community"),
    ]
    failed = tuple(msg for ok, msg in checks if not ok)
    if not failed:
        return Decision(Action.AUTO_APPROVE, ("all checks passed",), priority)

    # ---- 3. HUMAN REVIEW: the uncertain middle ---------------------------
    return Decision(Action.HUMAN_REVIEW, failed, priority)
