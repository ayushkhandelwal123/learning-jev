"""A stand-in for "send this message to the author": append it to a JSONL file.

In a real system this would call your forum's API or an email service. It is passed
into the graph as a plain function, so tests can swap it for a list.append.
"""

import json
import time
from pathlib import Path


class JsonlOutbox:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __call__(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({**record, "sent_at": time.time()}) + "\n")
