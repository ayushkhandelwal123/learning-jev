"""All decision thresholds in ONE place.

Keeping numbers out of the logic makes them easy to find, explain and tune.
(Level 4 will tune them against hand-labelled data instead of guessing.)

Scales:
  Noul values (is_spam, ...)  : 0.0 to 1.0, a probability
  toxicity (Score)            : 0.0 to 4.0, position on the 5-level rubric
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    # --- AUTO-REMOVE: any ONE of these is enough -------------------------
    spam_remove: float = 0.90
    personal_info_remove: float = 0.80
    toxicity_remove: float = 3.0

    # A Score is only trusted when Jev is at least this confident.
    toxicity_min_confidence: float = 0.60

    # --- AUTO-APPROVE: ALL of these must hold ----------------------------
    spam_approve_max: float = 0.15
    self_promotion_approve_max: float = 0.25
    personal_info_approve_max: float = 0.15
    toxicity_approve_max: float = 1.0

    # Everything that is neither removed nor approved goes to a human.
