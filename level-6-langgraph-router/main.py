"""Level 6: the moderation pipeline as a LangGraph workflow with human-in-the-loop.

Usage (from the repository root, venv active):
    python level-6-langgraph-router/main.py graph            # print the workflow diagram
    python level-6-langgraph-router/main.py run              # process posts; pause for humans
    python level-6-langgraph-router/main.py status           # who is waiting, what finished
    python level-6-langgraph-router/main.py review           # answer the waiting questions
    python level-6-langgraph-router/main.py run --no-llm     # skip drafting (no Groq calls)
    python level-6-langgraph-router/main.py run --every 5 --fresh   # 12 posts, a good mix

`run` and `review` are separate processes on purpose. Paused posts are saved in a
SQLite checkpoint file, so you can run, close the terminal, and review tomorrow.
"""

import argparse
import csv
import os
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from typesafe_sdk import (
    RetryPolicy,
    TypeSafeAuthenticationError,
    TypeSafeClient,
    TypeSafePermissionDeniedError,
)

from drafter import DraftError, Drafter
from graph import build_graph
from outbox import JsonlOutbox

load_dotenv()

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"  # git-ignored
DB_PATH = OUTPUT_DIR / "checkpoints.sqlite"
OUTBOX_PATH = OUTPUT_DIR / "outbox.jsonl"

SKIP, QUIT = "skip", "quit"


def load_posts(limit: int | None = None, every: int = 1) -> list[tuple[str, str]]:
    """Read posts.csv. The file is ordered (clean posts first, then violations, then
    borderline ones), so use `every` to sample across it instead of taking only the top."""
    with open(HERE / "posts.csv", newline="", encoding="utf-8") as f:
        posts = [(row["id"], row["text"]) for row in csv.DictReader(f)]
    posts = posts[::every]
    return posts[:limit] if limit else posts


def thread_config(post_id: str) -> dict:
    # One thread per post. The thread id is the key under which its progress is saved.
    return {"configurable": {"thread_id": f"post-{post_id}"}}


@contextmanager
def open_app(use_jev: bool, use_llm: bool):
    """Build the graph with a SQLite checkpoint store, and close everything afterwards."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    with SqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        client = None
        if use_jev:
            client = TypeSafeClient(retry=RetryPolicy(max_retries=4, backoff_initial=1.0,
                                                      backoff_max=20.0, timeout=90.0),
                                    timeout=30.0)
        drafter = None
        if use_llm:
            drafter = Drafter()
            try:
                drafter.verify_model()
            except DraftError as err:
                sys.exit(str(err))
        try:
            yield build_graph(client, drafter, checkpointer, JsonlOutbox(OUTBOX_PATH))
        finally:
            if client is not None:
                client.close()


# --------------------------------------------------------------------- summaries ----
def print_summary(app, posts) -> None:
    finished, waiting, untouched = Counter(), Counter(), 0
    for post_id, _ in posts:
        snap = app.get_state(thread_config(post_id))
        if not snap.values:
            untouched += 1
        elif snap.next:
            waiting[snap.next[0]] += 1
        else:
            finished[snap.values.get("outcome", "?")] += 1
    sent = 0
    if OUTBOX_PATH.exists():
        with open(OUTBOX_PATH, encoding="utf-8") as f:  # closed promptly (Windows is strict)
            sent = sum(1 for _ in f)
    print("\n" + "=" * 70)
    print("FINISHED:", dict(finished) or "none")
    print("WAITING FOR A HUMAN:", dict(waiting) or "none")
    if untouched:
        print("NOT STARTED:", untouched)
    print(f"MESSAGES SENT SO FAR: {sent}")
    if waiting:
        print("\nRun the 'review' command to answer the waiting posts.")


# ----------------------------------------------------------------------- commands ----
def cmd_graph(args) -> None:
    app = build_graph(None, None, None, lambda record: None)
    mermaid = app.get_graph().draw_mermaid()
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "graph.mmd").write_text(mermaid, encoding="utf-8")
    print(mermaid)
    print(f"(saved to {OUTPUT_DIR / 'graph.mmd'}; paste it into https://mermaid.live to see it)")


def cmd_run(args) -> None:
    if not os.getenv("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY not found. Check your .env file in the repo root.")
    if not args.no_llm and not os.getenv("GROQ_API_KEY"):
        sys.exit("GROQ_API_KEY not found. Add it to .env, or use --no-llm.")
    OUTPUT_DIR.mkdir(exist_ok=True)
    if args.fresh:
        for path in (DB_PATH, OUTBOX_PATH):
            path.unlink(missing_ok=True)

    if args.every < 1:
        sys.exit("--every must be at least 1.")
    posts = load_posts(args.limit, args.every)
    with open_app(use_jev=True, use_llm=not args.no_llm) as app:
        for post_id, text in posts:
            config = thread_config(post_id)
            before = app.get_state(config)
            if before.values:  # this post was already started by an earlier run
                where = f"waiting at '{before.next[0]}'" if before.next else "already finished"
                print(f"{post_id:<6} {where}, skipping")
                continue
            try:
                app.invoke({"post_id": post_id, "text": text, "log": []}, config)
            except (TypeSafeAuthenticationError, TypeSafePermissionDeniedError):
                sys.exit("TypeSafe rejected the API key. Check TYPESAFE_API_KEY in .env.")
            snap = app.get_state(config)
            if snap.next:
                print(f"{post_id:<6} {snap.values['action']:<13} WAITING at '{snap.next[0]}'")
            else:
                print(f"{post_id:<6} {snap.values['action']:<13} {snap.values['outcome']}")
        print_summary(app, posts)


def cmd_status(args) -> None:
    posts = load_posts()
    with open_app(use_jev=False, use_llm=False) as app:
        print_summary(app, posts)
        OUTPUT_DIR.mkdir(exist_ok=True)
        with open(OUTPUT_DIR / "report.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["post_id", "action", "status", "notice_sent", "reasons", "log", "text"])
            for post_id, text in posts:
                snap = app.get_state(thread_config(post_id))
                v = snap.values
                if not v:
                    status = "not started"
                elif snap.next:
                    status = f"waiting at {snap.next[0]}"
                else:
                    status = v.get("outcome", "?")
                writer.writerow([post_id, v.get("action", ""), status, v.get("notice_sent", ""),
                                 " | ".join(v.get("reasons", [])), " > ".join(v.get("log", [])), text])
        print(f"Saved the full report to {OUTPUT_DIR / 'report.csv'}")


def ask_choice(prompt: str, allowed: str, ask) -> str:
    while True:
        answer = ask(prompt).strip().lower()
        if answer and answer[0] in allowed:
            return answer[0]
        print(f"  please type one of: {', '.join(allowed)}")


def ask_moderator(payload: dict, ask=input):
    """Show one waiting post and return the resume value (or SKIP / QUIT)."""
    print("\n" + "=" * 70)
    print(f"POST {payload['post_id']}: {payload['text']}")
    print(f"Policy said: {payload['action']} ({'; '.join(payload['reasons'])})")
    if payload["draft"]:
        print("\nDRAFT MESSAGE:")
        for line in payload["draft"].splitlines():
            print(f"  {line}")
    for warning in payload["warnings"]:
        print(f"  WARNING: {warning}")

    if payload["type"] == "moderator":
        choice = ask_choice("\n[a]pprove post  [r]emove post  [s]kip  [q]uit > ", "arsq", ask)
        if choice == "s":
            return SKIP
        if choice == "q":
            return QUIT
        decision = "approve" if choice == "a" else "remove"
        message = ""
        if payload["draft"]:
            c = ask_choice("Message to the author: [y] send draft  [e] edit  [n] none > ", "yen", ask)
            message = payload["draft"] if c == "y" else ask("New message (one line): ").strip() if c == "e" else ""
        return {"decision": decision, "message": message}

    # approve_notice: the post was already removed automatically; only the message is in question
    choice = ask_choice("\nPost already removed. Notice: [y] send draft  [e] edit  [n] none  "
                        "[s]kip  [q]uit > ", "yensq", ask)
    if choice == "s":
        return SKIP
    if choice == "q":
        return QUIT
    if choice == "y":
        return {"message": payload["draft"]}
    if choice == "e":
        return {"message": ask("New message (one line): ").strip()}
    return {"message": ""}


def cmd_review(args, ask=input) -> None:
    posts = load_posts()
    with open_app(use_jev=False, use_llm=False) as app:
        pending = [pid for pid, _ in posts if app.get_state(thread_config(pid)).next]
        if not pending:
            print("Nothing is waiting for a human.")
            return
        print(f"{len(pending)} posts are waiting.")
        for post_id in pending:
            config = thread_config(post_id)
            payload = app.get_state(config).tasks[0].interrupts[0].value
            answer = ask_moderator(payload, ask)
            if answer == QUIT:
                break
            if answer == SKIP:
                continue
            app.invoke(Command(resume=answer), config)  # the graph continues from the pause
        print_summary(app, posts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("graph", help="Print the workflow diagram.").set_defaults(func=cmd_graph)
    run = sub.add_parser("run", help="Process posts; pause when a human is needed.")
    run.add_argument("--limit", type=int, help="Stop after N posts.")
    run.add_argument("--every", type=int, default=1,
                     help="Take every Nth post, to sample across the whole file (try 5).")
    run.add_argument("--no-llm", action="store_true", help="Skip drafting messages.")
    run.add_argument("--fresh", action="store_true", help="Delete saved progress first.")
    run.set_defaults(func=cmd_run)
    sub.add_parser("status", help="Show progress and write report.csv.").set_defaults(func=cmd_status)
    sub.add_parser("review", help="Answer the posts waiting for a human.").set_defaults(func=cmd_review)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()