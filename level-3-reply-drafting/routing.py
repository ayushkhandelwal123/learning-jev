"""NEW in Level 3: pick WHICH kind of message to draft.

This is the "Jev decides" half. Jev's signals and the policy decision choose a
ReplyKind. The LLM is never asked to decide anything, only to write.
Like policy.py, this file never calls an API, so it is testable offline.
"""

from enum import Enum

from config import Thresholds
from policy import Action, Decision, Signals


class ReplyKind(str, Enum):
    NO_REPLY = "no_reply"
    REMOVAL_PERSONAL_INFO = "removal_personal_info"
    REMOVAL_ABUSE = "removal_abuse"
    REMOVAL_SPAM = "removal_spam"
    REVIEW_TONE = "review_tone"
    REVIEW_PROMOTION = "review_promotion"
    REVIEW_OFFTOPIC = "review_offtopic"


def choose_reply_kind(s: Signals, d: Decision, t: Thresholds = Thresholds()) -> ReplyKind:
    # Clean posts need no message.
    if d.action is Action.AUTO_APPROVE:
        return ReplyKind.NO_REPLY

    # Removals: when several rules fired, privacy beats abuse beats spam.
    if d.action is Action.AUTO_REMOVE:
        if s.shares_personal_info >= t.personal_info_remove:
            return ReplyKind.REMOVAL_PERSONAL_INFO
        if s.toxicity >= t.toxicity_remove and s.toxicity_confidence >= t.toxicity_min_confidence:
            return ReplyKind.REMOVAL_ABUSE
        return ReplyKind.REMOVAL_SPAM

    # Human review: tone is the most sensitive, then promotion, then off-topic.
    if s.toxicity > t.toxicity_approve_max:
        return ReplyKind.REVIEW_TONE
    if s.post_type == "promotion" and s.is_self_promotion > t.self_promotion_approve_max:
        return ReplyKind.REVIEW_PROMOTION
    if s.post_type == "off_topic":
        return ReplyKind.REVIEW_OFFTOPIC
    return ReplyKind.NO_REPLY  # unclear case: the moderator decides, no draft
