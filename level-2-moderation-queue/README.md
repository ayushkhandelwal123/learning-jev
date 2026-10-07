# Level 2: Thresholds and a Human-Review Queue

Level 1 only displayed Jev's numbers. Level 2 turns them into decisions:

| Action | Meaning |
|--------|---------|
| `auto_remove` | A clear violation, hidden without a human |
| `auto_approve` | Clearly safe, published without a human |
| `human_review` | Everything uncertain, sorted so the worst is seen first |

## What you will learn

- Turning probabilities into actions with thresholds
- Why the uncertain middle band (human review) is the point, not a failure
- Separating "ask Jev" from "decide what to do" so the rules are testable offline
- Using `confidence` to avoid trusting shaky Score values
- Fixing Level 1's problems: missing community context, and spam vs self-promotion

## Files

| File | Purpose |
|------|---------|
| `config.py` | Every threshold in one place |
| `questions.py` | Jev questions (improved from Level 1) |
| `policy.py` | Pure decision logic: Signals in, Decision out |
| `sample_posts.py` | 14 sample posts |
| `main.py` | Runs Jev, applies the policy, prints a summary and queue, writes CSV |
| `test_policy.py` | Offline tests for the policy (no API key needed) |

## Run

From the repository root, with the virtual environment active:

```powershell
python level-2-moderation-queue\test_policy.py
python level-2-moderation-queue\main.py
```

Run the test first. It is instant and free. `main.py` writes
`level-2-moderation-queue\output\decisions.csv` (git-ignored).

## Experiments

1. Lower `spam_remove` from 0.90 to 0.60 and see which posts change action.
2. Raise `toxicity_approve_max` to 2.0. Does the sarcastic post now get approved?
3. Add a new rule in `policy.py` and a matching test in `test_policy.py` first.
4. Open `decisions.csv` in Excel and compare the numbers with the reasons column.
