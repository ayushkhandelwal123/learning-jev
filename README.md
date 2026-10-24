# Learning Jev

Hands-on, level-by-level projects for learning **Jev**, TypeSafe's decision model, in Python.

Jev does not write text. You send it a `state` (some text) plus typed questions
(`Choice`, `Noul`, `Score`), and it returns typed answers your code can branch on.
This repo builds one scenario, **moderating forum posts**, six times over. Each level
is a self-contained folder that adds one capability, so you can compare any two folders
to see exactly what changed.

## The six levels

| Level | Folder | What it adds | Key idea |
|-------|--------|--------------|----------|
| 1 | [`level-1-post-moderation`](level-1-post-moderation/) | The three question types on forum posts | Read the raw probabilities, not just the label |
| 2 | [`level-2-moderation-queue`](level-2-moderation-queue/) | Thresholds and a human-review queue | The uncertain middle band is the point |
| 3 | [`level-3-reply-drafting`](level-3-reply-drafting/) | A Groq LLM drafts the author message | Jev decides, the LLM only writes |
| 4 | [`level-4-evaluation`](level-4-evaluation/) | Labelled data, metrics, threshold tuning | Measure instead of guessing |
| 5 | [`level-5-production`](level-5-production/) | Async batching, retries, rate limits, caching | Failures must fail safe |
| 6 | [`level-6-langgraph-router`](level-6-langgraph-router/) | The pipeline as a LangGraph workflow | Pause for a human, resume later |

Each folder has its own README with a walkthrough, things to look for, and experiments.

## Setup (Windows, PowerShell)

Requires Python 3.10 or newer (`python --version`). Run from the repository root.

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Then open `.env` and fill in your keys:

```
TYPESAFE_API_KEY=your_typesafe_api_key
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=your_groq_model_name
```

| Key | Needed by |
|-----|-----------|
| `TYPESAFE_API_KEY` | Every level |
| `GROQ_API_KEY`, `GROQ_MODEL` | Levels 3, 5 and 6 (they draft messages with an LLM) |

Optional: `TYPESAFE_MODEL` pins a specific Jev model in Level 5.

If PowerShell blocks the activation script, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

In Command Prompt, activate with `venv\Scripts\activate.bat`. On macOS or Linux, use
`source venv/bin/activate`, `cp .env.example .env`, and forward slashes in paths.

`.env` is git-ignored, so your keys are never committed. Dependencies are pinned
because the TypeSafe SDK is young and minor versions have changed question types before.
Re-run `pip install -r requirements.txt` after pulling new levels.

## Run every level

Every level has offline tests that need no API keys. Run those first.

### Level 1: post moderation basics

```powershell
python level-1-post-moderation\main.py
```

### Level 2: thresholds and a review queue

```powershell
python level-2-moderation-queue\test_policy.py
python level-2-moderation-queue\main.py
```

### Level 3: Jev decides, the LLM writes

```powershell
python level-3-reply-drafting\test_routing.py
python level-3-reply-drafting\main.py --dry-run
python level-3-reply-drafting\main.py
```

`--dry-run` skips the LLM. The second command shows Jev's decisions and message routing only.

### Level 4: evaluation and tuning

```powershell
python level-4-evaluation\test_metrics.py
python level-4-evaluation\collect.py
python level-4-evaluation\evaluate.py
python level-4-evaluation\evaluate.py --source hard
python level-4-evaluation\tune.py
```

`collect.py` asks Jev about the 60 labelled posts once and caches the answers. After
that, `evaluate.py` and `tune.py` run offline and instantly.

### Level 5: production hygiene

```powershell
python level-5-production\test_resilience.py
python level-5-production\main.py --dry-run
python level-5-production\main.py
python level-5-production\main.py
```

Run the main script twice. The second run should answer almost everything from cache.
Check your own plan limits and set `--rps` and `--llm-rps` to match.

### Level 6: LangGraph with human approval

```powershell
python level-6-langgraph-router\test_graph.py
python level-6-langgraph-router\main.py graph
python level-6-langgraph-router\main.py run --every 5 --fresh
python level-6-langgraph-router\main.py status
python level-6-langgraph-router\main.py review
```

`posts.csv` is ordered (clean posts first), so `--every 5` samples across the whole file.
`run` and `review` are separate processes on purpose: paused posts are saved in a SQLite
checkpoint file, so you can review later.

## What I learned

**Question wording is the real interface.** In Level 1, a cricket post was never flagged
off-topic because I had never told Jev what the community was about. A post with one honest
app link scored 0.52 on "is this spam?" because spam and self-promotion were one question.
Most fixes were rewording a question, not changing code.

**Separate "ask the model" from "decide what to do".** The policy is a plain function from
numbers to an action. That made it testable offline, cheap to change, and easy to reuse
unchanged in Levels 3 to 6.

**Be asymmetric, and make "unknown" mean "ask a human".** Removing needs one strong signal,
but auto-approving needs every check to pass. A post that none of my questions described
(an offer to sell leaked data) still landed in review, though more by luck than design.

**Let the LLM write, never decide, and treat both ends as untrusted.** User text goes inside
delimiters so instructions in a post are ignored. LLM output goes through a guardrail that
flags leaked emails and phone numbers, and a human approves every message before it is sent.

**A perfect score on an easy dataset proves little.** The 40-post starter set scored 100%.
Twenty deliberately tricky posts scored 75%. That drop was the useful information. Held-out
test posts, and a weighted cost for mistakes (publishing a violation costs more than an
unneeded review), kept the tuning honest.

**Fixes cause regressions, so re-run both datasets.** Rewording the personal-information
question fixed a false removal but made two genuine removals drop to human review. Only the
second dataset caught it.

**Production is mostly about failure.** Cache keys fingerprint everything that affects an
answer (text, questions, model, prompt), so stale answers are never served. Identical posts
arriving together make one call instead of many. A failed call is never cached and never
approves a post. Concurrency and rate limits are different limits, and you usually need both.
Measure service time, not time spent queueing.

**In a graph, resuming re-runs the paused node from its first line.** So the pause nodes
contain nothing but the pause, and anything with a side effect (sending a message) is its own
node afterwards.

## Limitations

- The datasets are small (60 posts) and the labels are subjective. Treat the numbers as a
  teaching exercise, not a benchmark.
- Thresholds are starting points. They need re-tuning on your own community's data.
- The Level 6 command line handles one post at a time, and its SQLite checkpoints suit one
  machine, not a team of moderators.

## License

[MIT](LICENSE)
