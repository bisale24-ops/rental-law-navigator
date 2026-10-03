"""Append-only audit log: every extraction decision, every lookup, every change test, with a timestamp."""
import json
import pathlib
import time

PATH = pathlib.Path(__file__).resolve().parents[1] / "out" / "audit.jsonl"


def log(event, **fields):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with PATH.open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}) + "\n")
