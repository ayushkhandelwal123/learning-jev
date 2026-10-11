"""Files, loading and the signals cache.

Calling Jev costs money and time, so we ask it ONCE per labelled post and save
the answers to output/signals.json. Evaluating and tuning then run offline
and instantly, as many times as you like.
"""

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from questions import QUESTIONS

HERE = Path(__file__).parent
# Every file named labeled_posts*.csv in this folder is loaded:
#   labeled_posts.csv       -> source "starter" (easy, clear-cut posts)
#   labeled_posts_hard.csv  -> source "hard"    (tricky posts, written to break things)
OUTPUT_DIR = HERE / "output"  # git-ignored
CACHE_FILE = OUTPUT_DIR / "signals.json"

GOLD_ACTIONS = ("approve", "remove", "review")


@dataclass(frozen=True)
class LabeledPost:
    id: str
    split: str          # "dev" (used for tuning) or "test" (held out)
    text: str
    gold_action: str    # what a careful human moderator would do
    gold_post_type: str  # optional; blank when not labelled
    source: str = "starter"  # which CSV the post came from


def source_name(path: Path) -> str:
    return path.stem.removeprefix("labeled_posts").strip("_") or "starter"


def load_labeled(paths: list[Path] | None = None) -> list[LabeledPost]:
    posts, seen = [], set()
    for path in paths or sorted(HERE.glob("labeled_posts*.csv")):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["id"] in seen:
                    raise ValueError(f"duplicate post id {row['id']} in {path.name}")
                seen.add(row["id"])
                if row["gold_action"] not in GOLD_ACTIONS:
                    raise ValueError(f"{row['id']}: gold_action must be one of {GOLD_ACTIONS}")
                if row["split"] not in ("dev", "test"):
                    raise ValueError(f"{row['id']}: split must be 'dev' or 'test'")
                posts.append(LabeledPost(row["id"], row["split"], row["text"],
                                         row["gold_action"], row["gold_post_type"],
                                         source_name(path)))
    return posts


def questions_hash() -> str:
    """Fingerprint of the questions. If you edit questions.py, cached answers
    become stale, and this hash is how we notice."""
    payload = json.dumps({k: v.model_dump() for k, v in QUESTIONS.items()},
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_cache() -> dict:
    """Return {post_id: signals_dict}. Empty if missing or stale."""
    if not CACHE_FILE.exists():
        return {}
    data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    if data.get("questions_hash") != questions_hash():
        print("NOTE: questions.py changed since the cache was built. "
              "Ignoring the old cache; run collect.py again.")
        return {}
    return data["signals"]


def save_cache(signals: dict) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps({"questions_hash": questions_hash(), "signals": signals}, indent=1),
        encoding="utf-8",
    )
