# Level 1: Forum Post Moderation Basics

Sends 10 hand-written forum posts to Jev and prints every answer, so you can see how
the three question types behave.

## What you will learn

- `Choice`: pick one label from a fixed set (returns the label, probabilities, confidence)
- `Noul`: probability that a yes/no statement is true (0 to 1)
- `Score`: position on an ordered scale (fractional, with probabilities and confidence)
- Several questions can be asked in a single request

## Files

| File | Purpose |
|------|---------|
| `questions.py` | The four questions asked about each post |
| `sample_posts.py` | 10 sample posts, some deliberately ambiguous |
| `main.py` | Sends each post to Jev and prints the answers |

## Run

From the repository root, with the virtual environment active:

```powershell
python level-1-post-moderation\main.py
```

## Reading the output

```
post_type  : promotion (confidence 0.90)
             promotion=0.90, help_request=0.05, ...
is_spam    : 0.93
personal   : 0.02
toxicity   : 0.40 of 4 (nearest level 0: Friendly or neutral), confidence 0.80
```

(The numbers above are illustrative, not real output.)

- A Noul near 0.5 means Jev is undecided. Treat that as information, not an error.
- A Score such as 2.4 sits between level 2 and level 3, because it is the
  probability-weighted position across all levels.
- Watch posts P07 (sarcasm), P08 (promotion disguised as sharing) and P10 ("hello").

## Experiments

1. Reword two `criteria` descriptions in `questions.py` and see how probabilities move.
2. Add a `feature_request` option to `post_type`.
3. Run the script twice and compare the numbers.
4. Add your own tricky post to `sample_posts.py`.
