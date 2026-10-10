# Learning Jev

Hands-on projects for learning **Jev**, TypeSafe's decision model, one level at a time.
Jev does not write text. You send it a `state` (some text) plus typed questions
(`Choice`, `Noul`, `Score`), and it returns typed answers your code can branch on.

## Levels

| Level | Folder | What it covers | Status |
|-------|--------|----------------|--------|
| 1 | [`level-1-post-moderation`](level-1-post-moderation/) | The three question types on forum posts | Done |
| 2 | [`level-2-moderation-queue`](level-2-moderation-queue/) | Thresholds and a human-review queue | Done |
| 3 | [`level-3-reply-drafting`](level-3-reply-drafting/) | Jev routes, an LLM writes the response | |
| 4 | _coming_ | Evaluation against hand-labelled data | |
| 5 | _coming_ | Async, retries, rate limits, caching | |
| 6 | _coming_ | Jev as a router node in LangGraph | |

## One-time setup (Windows, PowerShell)

Run these from the repository root.

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and replace `your_api_key_here` with your real TypeSafe API key.

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
