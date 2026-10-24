"""Offline tests for the workflow. No API keys, no network, no files.

Usage (from the repository root):
    python level-6-langgraph-router/test_graph.py
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from typesafe_sdk import SystemOneResponse, TypeSafeAuthenticationError
import httpx2

from drafter import Draft, DraftError
from graph import build_graph


def expect(name: str, got, want) -> None:
    status = "ok  " if got == want else "FAIL"
    print(f"{status} {name}: expected {want}, got {got}")
    assert got == want, name


def jev(spam=0.02, promo=0.02, pii=0.01, tox=0.0, post_type="discussion") -> SystemOneResponse:
    return SystemOneResponse.model_validate({
        "model": "fake", "usage": {"input_tokens": 1, "output_tokens": 1}, "answers": {
            "post_type": {"type": "choice", "choice": post_type, "confidence": 0.9,
                          "probabilities": {post_type: 0.9}},
            "is_spam": {"type": "noul", "noul": spam},
            "is_self_promotion": {"type": "noul", "noul": promo},
            "shares_personal_info": {"type": "noul", "noul": pii},
            "toxicity": {"type": "score", "score": tox, "confidence": 1.0,
                         "legend": {0: "a"}, "probabilities": {0: 1.0}}}})


class FakeJev:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, 0

    def system_one(self, state, questions, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class FakeDrafter:
    model = "fake-llm"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def draft(self, kind, text):
        self.calls += 1
        if self.fail:
            raise DraftError("Groq rate limit reached (after retries).")
        return Draft(f"Hi, draft for {kind.value}.\n- The Moderation Team", (), 1, 1)


def make(response=None, drafter="default", error=None):
    sent = []
    app = build_graph(FakeJev(response, error), FakeDrafter() if drafter == "default" else drafter,
                      InMemorySaver(), sent.append)
    return app, sent


def start(app, post_id="P1", text="some post"):
    cfg = {"configurable": {"thread_id": post_id}}
    app.invoke({"post_id": post_id, "text": text, "log": []}, cfg)
    return cfg, app.get_state(cfg)


# --- 1. clean post: no pause, published, nothing sent --------------------------------
app, sent = make(jev())
cfg, snap = start(app)
expect("clean post is published without pausing", (snap.next, snap.values["outcome"]), ((), "published"))
expect("nothing was sent", sent, [])

# --- 2. obvious spam: removed at once, then a human approves the notice -------------
app, sent = make(jev(spam=0.97))
cfg, snap = start(app)
expect("spam is removed immediately", snap.values["outcome"], "removed")
expect("then the graph waits for the notice to be approved", snap.next, ("approve_notice",))
payload = snap.tasks[0].interrupts[0].value
expect("the moderator is shown the draft", payload["draft"].startswith("Hi, draft"), True)
expect("nothing is sent before approval", sent, [])
app.invoke(Command(resume={"message": "Hi, edited by a human.\n- The Moderation Team"}), cfg)
snap = app.get_state(cfg)
expect("after approval the graph is finished", snap.next, ())
expect("exactly one message was sent", len(sent), 1)
expect("the human's edit is what was sent", sent[0]["message"].startswith("Hi, edited"), True)

# --- 3. the moderator can decline to send a notice ------------------------------------
app, sent = make(jev(spam=0.97))
cfg, _ = start(app)
app.invoke(Command(resume={"message": ""}), cfg)
expect("declining sends nothing", (sent, app.get_state(cfg).values["notice_sent"]), ([], False))

# --- 4. borderline post: pauses for a verdict, approve it -------------------------------
app, sent = make(jev(tox=1.5))
cfg, snap = start(app)
expect("a borderline post waits for the moderator", snap.next, ("moderator",))
expect("the draft is ready for them", bool(snap.tasks[0].interrupts[0].value["draft"]), True)
app.invoke(Command(resume={"decision": "approve", "message": "Hi, please keep it friendly."}), cfg)
snap = app.get_state(cfg)
expect("approve publishes the post", snap.values["outcome"], "published")
expect("and the human-approved message is sent", len(sent), 1)

# --- 5. same, but the moderator removes it with no message --------------------------------
app, sent = make(jev(tox=1.5))
cfg, _ = start(app)
app.invoke(Command(resume={"decision": "remove"}), cfg)
snap = app.get_state(cfg)
expect("remove removes the post", snap.values["outcome"], "removed")
expect("no message means nothing sent", sent, [])

# --- 6. a bad resume value is rejected, not guessed ----------------------------------------
app, sent = make(jev(tox=1.5))
cfg, _ = start(app)
try:
    app.invoke(Command(resume={"decision": "maybe"}), cfg)
    raise AssertionError("expected an error")
except ValueError:
    print("ok   an invalid decision is rejected")
expect("the post is still waiting after a bad answer", app.get_state(cfg).next, ("moderator",))

# --- 7. failure paths all fail safe -----------------------------------------------------------
app, sent = make(error=RuntimeError("server on fire"))
cfg, snap = start(app)
expect("a Jev failure goes to a human, not to approval", snap.next, ("moderator",))
expect("the reason is recorded", "processing failed" in snap.values["reasons"][0], True)

app, sent = make(jev(tox=1.5), drafter=FakeDrafter(fail=True))
cfg, snap = start(app)
expect("a failed draft still reaches the moderator", snap.next, ("moderator",))
expect("the failure is shown as a warning", snap.values["warnings"][0].startswith("draft failed"), True)

# --- 8. no-LLM mode -------------------------------------------------------------------------
app, sent = make(jev(spam=0.97), drafter=None)
cfg, snap = start(app)
expect("without a drafter, a removal just finishes", (snap.next, snap.values["outcome"]), ((), "removed"))
app, sent = make(jev(tox=1.5), drafter=None)
cfg, snap = start(app)
expect("without a drafter, review goes straight to the moderator", snap.next, ("moderator",))

# --- 9. a rejected API key is fatal: it raises instead of hiding in the queue -------------------
app, sent = make(error=TypeSafeAuthenticationError(401, {}, httpx2.Headers()))
try:
    start(app)
    raise AssertionError("expected an error")
except TypeSafeAuthenticationError:
    print("ok   a rejected API key stops the run")

# --- 10. interrupt nodes re-run on resume; side-effect nodes must not -----------------------------
app, sent = make(jev(spam=0.97))
cfg, snap = start(app)
app.invoke(Command(resume={"message": "Hi."}), cfg)
expect("resuming did not send the message twice", len(sent), 1)

# --- 11. the audit log accumulates (a reducer, not an overwrite) -------------------------------
log = app.get_state(cfg).values["log"]
expect("every node left a log line", [line.split(":")[0] for line in log],
       ["classify", "decide", "remove_post", "draft", "approve_notice", "send_notice"])

# --- 12. the graph can draw itself ---------------------------------------------------------------
mermaid = app.get_graph().draw_mermaid()
expect("the diagram contains the interrupt nodes", ("moderator" in mermaid, "approve_notice" in mermaid), (True, True))

print("\nAll graph tests passed.")
