# Level 5: Production Hygiene
 
Levels 1 to 4 handled a few dozen posts one at a time. Level 5 runs the whole
pipeline (Jev signals, policy, routing, LLM drafts) at volume and makes it survive
the real world: slow responses, rate limits, outages, duplicates and crashes.
 
```
posts.csv -> [cache?] Jev -> policy -> routing -> [cache?] Groq draft -> results.csv
              ^ concurrency limit + rate limit + SDK retries on both calls ^
```
 
## What you will learn
 
- **Async concurrency** with a limit on how many posts are in flight
- **Rate limiting** on the client side, so you rarely see a 429 at all
- **Retries**: the TypeSafe SDK has a built-in `RetryPolicy` (backoff, jitter,
  `Retry-After`), so we configure it instead of writing our own loop
- **A persistent cache** (SQLite) keyed by everything that affects an answer, so
  re-runs, crash recovery and reposts are free
- **Single-flight de-duplication**: identical posts arriving together make one call
- **Fail-safe errors**: a post we could not process goes to a human, never to approve
- **Fatal vs transient errors**: a rejected API key stops the run, a timeout does not
- **A run manifest** (versions, model, questions hash, thresholds) for reproducibility
## Files
 
| File | Purpose |
|------|---------|
| `cache.py` | **New:** SQLite cache, cache keys, and single-flight de-duplication |
| `limiter.py` | **New:** client-side rate limiter |
| `pipeline.py` | **New:** async per-post pipeline with fail-safe error handling |
| `main.py` | **New:** runs the batch, prints a summary, writes results and a manifest |
| `drafter.py` | Level 3's file plus an async `adraft()` method |
| `posts.csv` | The 60 posts from Level 4's two label files (text only) |
| `config.py`, `questions.py`, `policy.py` | Copied from Level 4 |
| `routing.py`, `prompts.py` | Copied from Level 3 |
| `test_resilience.py` | **New:** offline tests for the cache, limiter and fail-safe logic |
 
If you changed thresholds in Level 4's `config.py` after tuning, copy your version
into this folder, so Level 5 uses the numbers you chose.
 
## Setup
 
No new packages. Your `.env` needs `TYPESAFE_API_KEY`, `GROQ_API_KEY` and
`GROQ_MODEL`. One optional extra setting:
 
```
TYPESAFE_MODEL=<a Jev model name>
```
 
Leave it unset to use the SDK default. The first run prints the list of available
Jev models, so you can copy a name from there to pin it.
 
## Run
 
From the repository root, with the virtual environment active:
 
```powershell
python level-5-production\test_resilience.py
python level-5-production\main.py --dry-run
python level-5-production\main.py
python level-5-production\main.py
```
 
Run the main script twice. The second run should make almost no API calls.
 
| Flag | Meaning | Default |
|------|---------|---------|
| `--concurrency N` | Max posts in flight at once | 5 |
| `--rps N` | Max Jev requests started per second | 5 |
| `--llm-rps N` | Max Groq requests started per second | 1 |
| `--limit N` | Only the first N posts | all |
| `--copies N` | Repeat every post N times (to see de-duplication) | 1 |
| `--dry-run` | Skip the LLM drafting step | off |
| `--no-cache` | Ignore and do not write the cache | off |
 
The defaults for `--rps` and `--llm-rps` are cautious guesses. Check your own plan's
limits in the TypeSafe and Groq consoles and set them to match.
 
## Reading the output
 
- **WHERE ANSWERS CAME FROM:** `api` is a real call, `cache` came from disk,
  `deduped` shared a call already in flight.
- **TIMING:** posts per second, and median and p95 latency for posts that needed a
  Jev call (measured from when a post gets a worker slot, so queueing is excluded).
  p95 is the slow tail, the number users actually feel.
- **Rate-limit floor:** the fastest the run could finish given your `--rps` and
  `--llm-rps`. If the total time is close to the floor, the limiter is your
  bottleneck, not the API. Raise the rate if your plan allows it.
- **drafts that FAILED:** drafts that errored after the retries. They are not
  cached, so simply running again retries only those.
- **TOKENS:** counted only for real calls. Cached answers cost nothing.
- **errors:** posts that failed after the SDK's retries. They are sent to human
  review, never approved.
- `output\run_manifest.json` records versions, models, the questions hash and the
  thresholds, so you can say exactly what produced a result.
## Why each limit exists
 
| Limit | Protects against |
|-------|------------------|
| Concurrency | Opening too many connections, and memory use at scale |
| Rate limit | 429 errors, which cost time even when retried |
| SDK retries | Brief outages, timeouts and the occasional 429 |
| Cache | Paying twice for the same answer, and starting over after a crash |
| Single-flight | A burst of identical posts making identical calls |
| Fail-safe | An outage silently approving everything |
 
## Experiments
 
1. Run twice and compare "WHERE ANSWERS CAME FROM".
2. `--copies 3` and watch `deduped` appear alongside `cache`.
3. `--concurrency 1` against `--concurrency 10`: compare total time.
4. `--rps 1` shows the limiter becoming the bottleneck.
5. Press Ctrl+C part-way through a run, then run again. Finished posts are cached,
   so it resumes.
6. Change one word in a question: every signal becomes a cache miss. Change a
   threshold in `config.py`: no new calls at all.
7. Put a wrong value in `TYPESAFE_API_KEY`. The run should abort quickly.
## Limits of this design
 
- `asyncio.gather` over every post is fine for thousands, but for millions use a
  queue with a fixed pool of workers, so memory stays flat.
- If you do not pin `TYPESAFE_MODEL`, the cache key says "default-model". If the SDK
  default silently moves to a newer model, old cached signals would still be served.
  Pinning removes that risk, and the manifest records which model answered.
- The cache has no expiry and lives in one SQLite file, which suits one machine and
  one process. Several workers need a shared store such as Redis or a database.
- Retry counts inside the SDK are not visible here, so a slow run could be retries.
  Watch the p95 latency.
  