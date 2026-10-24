# Learning Jev

Hands-on projects for learning **Jev**, TypeSafe's decision model, one level at a time.
Jev does not write text. You send it a `state` (some text) plus typed questions
(`Choice`, `Noul`, `Score`), and it returns typed answers your code can branch on.

## Levels

| Level | Folder | What it covers | Status |
|-------|--------|----------------|--------|
| 1 | [`level-1-post-moderation`](level-1-post-moderation/) | The three question types on forum posts | Done |
| 2 | [`level-2-moderation-queue`](level-2-moderation-queue/) | Thresholds and a human-review queue | Done |
| 3 | [`level-3-reply-drafting`](level-3-reply-drafting/) | Jev routes, a Groq LLM drafts the message | Done |
| 4 | [`level-4-evaluation`](level-4-evaluation/) | Evaluation and threshold tuning on labelled data | Done |
| 5 | [`level-5-production`](level-5-production/) | Async batching, retries, rate limits, caching, fail-safe errors | Done |
| 6 | [`level-6-langgraph-router`](level-6-langgraph-router/) | Jev as a router node in LangGraph, with human approval | Done |

## One-time setup (Windows, PowerShell)

Run these from the repository root.

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and fill in your real keys. Level 3 onwards also needs `GROQ_API_KEY` and `GROQ_MODEL`. Re-run `pip install -r requirements.txt` whenever a level adds packages (Level 6 adds LangGraph).

If PowerShell blocks the activation script, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

With Command Prompt (cmd), activate with `venv\Scripts\activate.bat` instead.

## Run a level

```powershell
python level-1-post-moderation\main.py
```

## Notes

- `.env` is git-ignored. Only `.env.example` is committed.
- Dependencies are pinned because the TypeSafe SDK is young and minor versions have
  changed question types before.
- Requires Python 3.10 or newer (check with `python --version`).
