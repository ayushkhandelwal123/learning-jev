"""The graph's shared state: one dictionary that every node reads and updates.

A node returns only the keys it wants to CHANGE. LangGraph merges them in.
Most keys are simply overwritten. `log` has a reducer (operator.add), so each node's
entries are APPENDED instead, which gives a free audit trail.
"""

import operator
from typing import Annotated, TypedDict


class ModerationState(TypedDict, total=False):
    # --- input -------------------------------------------------------------
    post_id: str
    text: str
    # --- filled in by nodes ------------------------------------------------
    signals: dict            # Jev's answers as plain numbers
    error: str               # set if Jev failed, so the post fails safe to a human
    action: str              # auto_approve | auto_remove | human_review
    reasons: list[str]
    kind: str                # which message to draft (a ReplyKind value)
    draft: str               # the LLM's draft message
    warnings: list[str]      # guardrail findings about the draft
    verdict: str             # the moderator's decision: approve | remove
    final_message: str       # the message a human approved (empty = send nothing)
    outcome: str             # published | removed
    notice_sent: bool
    log: Annotated[list[str], operator.add]
