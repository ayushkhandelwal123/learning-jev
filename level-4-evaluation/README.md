# Level 4: Evaluation and Threshold Tuning

Levels 2 and 3 used thresholds that I chose as sensible guesses. Level 4 measures
them. You compare what the policy does with what a careful human moderator would
do, count the mistakes that matter, and search for better thresholds.

```
labeled_posts.csv --> collect.py --> output/signals.json --> evaluate.py
 (gold labels)       (Jev, run once)   (cached answers)  --> tune.py
```

## What you will learn

- Building a small labelled ("gold") dataset and why it is the most valuable asset
- Separating the paid step (asking Jev) from the free steps (evaluating, tuning)
- A confusion matrix, and why different mistakes should have different costs
- Tuning thresholds on a **dev** split and checking on a held-out **test** split
- How the cost weights you pick decide what the tuner optimises

## Files

| File | Purpose |
|------|---------|
| `labeled_posts.csv` | 40 easy "starter" posts with gold labels (dev 27, test 13) |
| `labeled_posts_hard.csv` | 20 tricky posts written to break the system (dev 14, test 6) |
| `store.py` | File paths, CSV loading, and the signals cache |
| `metrics.py` | Pure evaluation maths and the `ERROR_COSTS` weights |
| `collect.py` | **Step 1:** asks Jev about each post once and caches the answers |
| `evaluate.py` | **Step 2:** scores the current thresholds against the gold labels |
| `tune.py` | **Step 3:** searches 1,200 threshold combinations on dev, checks on test |
| `test_metrics.py` | Offline tests for the maths |
| `config.py`, `questions.py`, `policy.py` | Copied unchanged from Level 3 |

## Run

From the repository root, with the virtual environment active. No new packages.

```powershell
python level-4-evaluation\test_metrics.py
python level-4-evaluation\collect.py
python level-4-evaluation\evaluate.py
python level-4-evaluation\tune.py
```

Compare the two sets separately. Starter posts show the system works on clear cases;
hard posts show where it breaks:

```powershell
python level-4-evaluation\evaluate.py --source starter
python level-4-evaluation\evaluate.py --source hard
```

`collect.py` makes one Jev call per labelled post that is not cached yet (about 40 for
the starter set, 20 more for the hard set). After that, `evaluate.py` and
`tune.py` run offline and instantly. If you edit `questions.py`, the cache is
detected as stale and you re-run `collect.py`.

## How the gold labels work

Each post has a `gold_action`: what a careful human moderator would do.

| Label | Meaning |
|-------|---------|
| `approve` | Fine to publish |
| `remove` | Clear violation: spam, personal information, threats or abuse |
| `review` | Borderline: sarcasm, promotion, rudeness, off-topic |

**The labels are my judgement, not yours.** Open `labeled_posts.csv` in Excel or
VS Code and change any label you disagree with. Your community's rules, not mine,
should decide. Then add your own posts: keep the same columns, use `dev` or `test`
for `split`, and keep the text plain ASCII. Re-run `collect.py` to pick up new rows.

Every `labeled_posts*.csv` file in the folder is loaded, so you can add your own
`labeled_posts_mine.csv` with the same columns (a `note` column is optional).

Sixty posts is enough to learn the method but too small to trust a result. Aim for
150 or more if you ever use this on a real community.

## Reading the results

- **Confusion matrix:** rows are the gold label, columns are what the policy did.
  The diagonal is correct. The `remove` row under `approve` is the worst cell: a
  violation was published.
- **Automation rate:** the share of posts that needed no human. This is the
  business benefit.
- **Weighted mistake cost:** mistakes are not equal, so `ERROR_COSTS` in
  `metrics.py` gives each a weight (publishing a violation 10, wrongly removing a
  good post 5, skipping review on a borderline post 3). A post sent to a human
  unnecessarily costs 0, because it costs time, not harm.
- **Defaults vs tuned:** the key table in `tune.py`. If tuned thresholds win on
  dev but lose on test, they memorised the dev posts.

## Experiments

1. Change the weights in `ERROR_COSTS` (say, make wrongful removals cost 20) and see
   how the recommended thresholds move.
2. Relabel three posts you genuinely disagree with and re-run `evaluate.py`.
3. Add 10 of your own tricky posts, one in each gold category.
4. Widen `GRID` in `tune.py` and check whether the best result stays stable.
5. Look at the `MISTAKES` section for the posts the policy gets wrong and decide
   whether the fix is a threshold, a question wording, or a gold label.
