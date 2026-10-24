"""The Level 6 workflow as a LangGraph state graph.

                            +--> publish ------------------------------------+
                            |                                                |
  START -> classify -> decide --> remove_post --> draft --> approve_notice --+--> send_notice -> END
                            |                       ^  (interrupt)           |
                            +--> draft ------------>+--> moderator --> apply_verdict
                                 (review path)         (interrupt)

Everything Levels 1 to 5 built is reused as ordinary Python functions inside nodes.
What the graph adds:
  * CONDITIONAL EDGES: the routing from Levels 2 and 3 is now an explicit, drawable map.
  * INTERRUPTS: the graph pauses for a human and resumes later, even from another process.
  * CHECKPOINTS: every step is saved, so a paused post survives a restart.

Rules for nodes that contain interrupt():
  When the graph resumes, the interrupting node runs again FROM ITS FIRST LINE.
  So an interrupt node does no side effects before interrupt(), and anything with a
  side effect (sending a message) lives in a separate node AFTER it.
"""

from dataclasses import asdict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typesafe_sdk import TypeSafeAuthenticationError, TypeSafePermissionDeniedError

from config import Thresholds
from drafter import DraftError
from policy import Action, Signals, extract_signals
from policy import decide as apply_policy
from questions import QUESTIONS
from routing import ReplyKind, choose_reply_kind
from state import ModerationState


def build_graph(client, drafter, checkpointer, send, thresholds: Thresholds = Thresholds()):
    """Wire the nodes together.

    client       a TypeSafeClient (or a fake in tests)
    drafter      a Drafter, or None for "do not draft messages"
    checkpointer where paused runs are saved (SQLite, or in-memory for tests)
    send         a function that delivers an approved message
    """

    def can_draft(state: ModerationState) -> bool:
        return drafter is not None and state["kind"] != ReplyKind.NO_REPLY.value

    def payload(state: ModerationState, kind: str) -> dict:
        """What the moderator is shown when the graph pauses. Must be JSON-friendly."""
        return {
            "type": kind, "post_id": state["post_id"], "text": state["text"],
            "action": state["action"], "reasons": state.get("reasons", []),
            "reply_kind": state["kind"], "draft": state.get("draft", ""),
            "warnings": state.get("warnings", []),
        }

    # ---------------------------------------------------------------- nodes ----
    def classify(state: ModerationState) -> dict:
        """Ask Jev. (Level 1)"""
        try:
            response = client.system_one(state=state["text"], questions=QUESTIONS)
        except (TypeSafeAuthenticationError, TypeSafePermissionDeniedError):
            raise  # a rejected key is fatal: stop, do not quietly send everything to humans
        except Exception as err:
            return {"error": f"{type(err).__name__}: {err}",
                    "log": [f"classify: Jev failed ({type(err).__name__})"]}
        signals = extract_signals(response)
        return {"signals": asdict(signals),
                "log": [f"classify: spam={signals.is_spam:.2f} "
                        f"pii={signals.shares_personal_info:.2f} tox={signals.toxicity:.2f}"]}

    def decide(state: ModerationState) -> dict:
        """Apply the policy and pick the message kind. (Levels 2 and 3, pure functions)"""
        if state.get("error"):  # fail safe: an error is not an approval
            return {"action": Action.HUMAN_REVIEW.value, "kind": ReplyKind.NO_REPLY.value,
                    "reasons": ["processing failed: a human must check this post"],
                    "log": ["decide: failed safe to human review"]}
        signals = Signals(**state["signals"])
        decision = apply_policy(signals, thresholds)
        kind = choose_reply_kind(signals, decision, thresholds)
        return {"action": decision.action.value, "kind": kind.value,
                "reasons": list(decision.reasons),
                "log": [f"decide: {decision.action.value}, message kind {kind.value}"]}

    def publish(state: ModerationState) -> dict:
        return {"outcome": "published", "log": ["publish: post is live"]}

    def remove_post(state: ModerationState) -> dict:
        return {"outcome": "removed", "log": ["remove_post: removed automatically"]}

    def draft(state: ModerationState) -> dict:
        """Ask the LLM to write the message. (Level 3)"""
        try:
            result = drafter.draft(ReplyKind(state["kind"]), state["text"])
        except DraftError as err:
            return {"draft": "", "warnings": [f"draft failed: {err}"],
                    "log": ["draft: failed, continuing without a draft"]}
        return {"draft": result.text, "warnings": list(result.warnings),
                "log": [f"draft: wrote {len(result.text)} characters"]}

    def approve_notice(state: ModerationState) -> dict:
        """PAUSE: a human approves or edits the notice for an auto-removed post."""
        answer = interrupt(payload(state, "approve_notice")) or {}
        message = (answer.get("message") or "").strip()
        return {"final_message": message,
                "log": ["approve_notice: " + ("message approved" if message else "no message")]}

    def moderator(state: ModerationState) -> dict:
        """PAUSE: a human decides about a borderline post."""
        answer = interrupt(payload(state, "moderator")) or {}
        decision = answer.get("decision")
        if decision not in ("approve", "remove"):
            raise ValueError("resume value must contain decision='approve' or 'remove'")
        return {"verdict": decision, "final_message": (answer.get("message") or "").strip(),
                "log": [f"moderator: decided to {decision}"]}

    def apply_verdict(state: ModerationState) -> dict:
        outcome = "published" if state["verdict"] == "approve" else "removed"
        return {"outcome": outcome, "log": [f"apply_verdict: post {outcome}"]}

    def send_notice(state: ModerationState) -> dict:
        """The only node with a side effect, kept separate from the interrupts."""
        message = state.get("final_message", "")
        if message:
            send({"post_id": state["post_id"], "outcome": state["outcome"], "message": message})
        return {"notice_sent": bool(message),
                "log": ["send_notice: " + ("sent" if message else "nothing to send")]}

    # ------------------------------------------------------- routing functions ----
    def after_decide(state: ModerationState) -> str:
        if state["action"] == Action.AUTO_APPROVE.value:
            return "publish"
        if state["action"] == Action.AUTO_REMOVE.value:
            return "remove_post"
        return "draft" if can_draft(state) else "moderator"

    def after_remove(state: ModerationState) -> str:
        return "draft" if can_draft(state) else END

    def after_draft(state: ModerationState) -> str:
        if state["action"] == Action.AUTO_REMOVE.value:
            return "approve_notice" if state.get("draft") else END
        return "moderator"

    # ------------------------------------------------------------------ wiring ----
    graph = StateGraph(ModerationState)
    for name, fn in (("classify", classify), ("decide", decide), ("publish", publish),
                     ("remove_post", remove_post), ("draft", draft),
                     ("approve_notice", approve_notice), ("moderator", moderator),
                     ("apply_verdict", apply_verdict), ("send_notice", send_notice)):
        graph.add_node(name, fn)

    graph.add_edge(START, "classify")
    graph.add_edge("classify", "decide")
    graph.add_conditional_edges("decide", after_decide, ["publish", "remove_post", "draft", "moderator"])
    graph.add_edge("publish", END)
    graph.add_conditional_edges("remove_post", after_remove, ["draft", END])
    graph.add_conditional_edges("draft", after_draft, ["approve_notice", "moderator", END])
    graph.add_edge("approve_notice", "send_notice")
    graph.add_edge("moderator", "apply_verdict")
    graph.add_edge("apply_verdict", "send_notice")
    graph.add_edge("send_notice", END)
    return graph.compile(checkpointer=checkpointer)
