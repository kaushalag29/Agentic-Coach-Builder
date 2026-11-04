"""Label an item sheet with the judge panel instead of by hand (ADR-0023, validation without human labels).

    export LAYA_EXPERIMENT_OUT=data/experiments/tagcheck        # keeps these votes apart from the Laya experiment's
    python experiments/laya/panel_sheet.py prepare data/reports/domain-labels-items-DATE.csv
    python experiments/laya/jury.py --max-cost 3                  # three blind judges vote on every row, resumable
    python experiments/laya/panel_sheet.py fill data/reports/domain-labels-items-DATE.csv

`prepare` turns the sheet (`ytbrain domains sample --n 300`) into the sample the jury reads. `fill` writes each row's
`label`: the Domains at least two of the three judges named (as primary or secondary). A row where no Domain
reaches two votes stays empty, so `ytbrain eval tags` skips it: the panel's disagreements never become ground truth.
Then `ytbrain eval tags --items SHEET --compare` scores the tags in use and the staged run on those labels.
Nothing here is imported by `ytbrain`; the text it handles is Library text, so it stays under data/ (git-ignored).
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import JURY, SAMPLE, read_jsonl, write_jsonl  # noqa: E402


def read_sheet(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def prepare(path: Path) -> int:
    _cols, rows = read_sheet(path)
    items = [{"item_id": r["item_id"], "text": r.get("text") or ""} for r in rows if r.get("item_id")]
    write_jsonl(SAMPLE, items)
    print(f"panel_sheet: {len(items)} item(s) in {SAMPLE}; next: python experiments/laya/jury.py")
    return 0


def majority(votes: list[dict], need: int = 2) -> list[str]:
    """The Domains named (primary or secondary) by at least `need` of the judges, in a fixed order."""
    named = Counter()
    for v in votes:
        for d in {v["primary"], v.get("secondary")} - {None}:
            named[d] += 1
    return sorted(d for d, n in named.items() if n >= need)


def fill(path: Path) -> int:
    cols, rows = read_sheet(path)
    by_item: dict[str, list[dict]] = {}
    for v in read_jsonl(JURY):
        by_item.setdefault(v["item_id"], []).append(v)
    done = left = 0
    for r in rows:
        votes = by_item.get(r["item_id"], [])
        label = majority(votes) if len(votes) >= 3 else []
        r["label"] = "|".join(label)
        done += bool(label)
        left += not label
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
    print(f"panel_sheet: {done} row(s) labelled by the panel in {path}; {left} left empty (too few votes, or no "
          f"Domain reached two)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["prepare", "fill"])
    ap.add_argument("sheet", type=Path)
    a = ap.parse_args()
    return prepare(a.sheet) if a.mode == "prepare" else fill(a.sheet)


if __name__ == "__main__":
    sys.exit(main())
