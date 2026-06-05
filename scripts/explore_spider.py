#!/usr/bin/env python3
"""Explore a Spider-format dataset: counts, schemas, query complexity.

Works against either the full download (data/spider) or the sample
(data/spider_sample). Run:

    python scripts/explore_spider.py --data-dir data/spider_sample
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Make `backend` importable when run from project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.utils.complexity import classify_sql  # noqa: E402

try:
    from rich.console import Console
    from rich.table import Table
    _console = Console()

    def out(msg=""):
        _console.print(msg)
except ImportError:  # graceful fallback if rich isn't installed
    Table = None

    def out(msg=""):
        print(msg if isinstance(msg, str) else str(msg))


def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def parse_schema(db: dict) -> dict:
    """Turn Spider's flat column format into {table: [(col, type), ...]}."""
    tables = db["table_names_original"]
    cols = db["column_names_original"]
    types = db.get("column_types", [])
    schema: dict[str, list[tuple[str, str]]] = {t: [] for t in tables}
    for idx, (tbl_idx, col_name) in enumerate(cols):
        if tbl_idx == -1:  # the synthetic "*" column
            continue
        col_type = types[idx] if idx < len(types) else "?"
        schema[tables[tbl_idx]].append((col_name, col_type))
    return schema


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/spider")
    ap.add_argument("--show-schemas", type=int, default=2,
                    help="how many DB schemas to print in full")
    ap.add_argument("--show-examples", type=int, default=3,
                    help="how many example questions to print")
    args = ap.parse_args()

    root = Path(args.data_dir)
    if not root.exists():
        out(f"[!] data dir not found: {root}")
        out("    Run scripts/make_sample_spider.py or scripts/download_spider.sh first.")
        sys.exit(1)

    tables = load_json(root / "tables.json") or []
    dev = load_json(root / "dev.json") or []
    train = load_json(root / "train_spider.json") or []
    examples = dev + train

    out("=" * 60)
    out(f"SPIDER DATASET EXPLORATION  ({root})")
    out("=" * 60)

    # ---- 1. Dataset-level counts ----
    n_db = len(tables)
    n_tables = sum(len(d["table_names_original"]) for d in tables)
    out("\n[1] Dataset size")
    out(f"    databases ............ {n_db}")
    out(f"    tables (total) ....... {n_tables}")
    out(f"    dev examples ......... {len(dev)}")
    out(f"    train examples ....... {len(train)}")
    out(f"    total examples ....... {len(examples)}")

    # ---- 2. Per-database structure ----
    out("\n[2] Databases (first %d shown in full)" % args.show_schemas)
    for i, db in enumerate(tables):
        schema = parse_schema(db)
        n_fk = len(db.get("foreign_keys", []))
        marker = "  ->" if i < args.show_schemas else "    "
        out(f"{marker} {db['db_id']}: {len(schema)} tables, {n_fk} foreign keys")
        if i < args.show_schemas:
            for tname, cols in schema.items():
                col_str = ", ".join(f"{c}:{t}" for c, t in cols)
                out(f"        {tname}({col_str})")

    # ---- 3. Query complexity distribution (our 5 tiers) ----
    out("\n[3] Gold-query complexity (project 5-tier classifier)")
    tier_counts: Counter[int] = Counter()
    feature_counts: Counter[str] = Counter()
    for ex in examples:
        res = classify_sql(ex.get("query", ""))
        tier_counts[res.tier] += 1
        for f in res.features:
            feature_counts[f] += 1
    total = sum(tier_counts.values()) or 1
    for tier in range(1, 6):
        c = tier_counts.get(tier, 0)
        bar = "#" * int(40 * c / total)
        out(f"    Tier {tier}: {c:>5}  {bar}")
    out(f"    feature hits: {dict(feature_counts)}")
    out("    (NOTE: for paper-comparable hardness, vendor Spider's "
        "evaluation.py eval_hardness in Week 4)")

    # ---- 4. Example questions ----
    out("\n[4] Sample questions")
    for ex in examples[: args.show_examples]:
        res = classify_sql(ex.get("query", ""))
        out(f"    db={ex['db_id']}  [{res.label}]")
        out(f"      Q: {ex['question']}")
        out(f"      SQL: {ex['query']}")

    out("\n" + "=" * 60)
    out("Exploration complete.")


if __name__ == "__main__":
    main()
