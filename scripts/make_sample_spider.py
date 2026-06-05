#!/usr/bin/env python3
"""Generate a small, faithful Spider-format sample dataset.

Why this exists: the full Spider archive is ~1GB and lives on Google Drive.
For local dev, tests, and CI we want a tiny dataset that exactly matches
Spider's on-disk layout (tables.json, dev.json, database/<id>/<id>.sqlite)
so code paths are exercised identically.

Output goes to data/spider_sample/ by default to avoid clobbering a real
download in data/spider/.

Run:  python scripts/make_sample_spider.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
#  tables.json — Spider's schema description format.
#  column_names_original is a list of [table_index, column_name]; index -1 is
#  the synthetic "*" column. primary_keys / foreign_keys reference positions
#  in that flat column list.
# ---------------------------------------------------------------------------
TABLES = [
    {
        "db_id": "college_1",
        "table_names_original": ["student", "course", "enrollment"],
        "table_names": ["student", "course", "enrollment"],
        "column_names_original": [
            [-1, "*"],
            [0, "student_id"], [0, "name"], [0, "gpa"],          # 1,2,3
            [1, "course_id"], [1, "title"], [1, "credits"],      # 4,5,6
            [2, "enroll_id"], [2, "student_id"],                 # 7,8
            [2, "course_id"], [2, "grade"],                      # 9,10
        ],
        "column_names": [
            [-1, "*"],
            [0, "student id"], [0, "name"], [0, "gpa"],
            [1, "course id"], [1, "title"], [1, "credits"],
            [2, "enroll id"], [2, "student id"],
            [2, "course id"], [2, "grade"],
        ],
        "column_types": [
            "text",
            "number", "text", "number",
            "number", "text", "number",
            "number", "number",
            "number", "text",
        ],
        "primary_keys": [1, 4, 7],
        "foreign_keys": [[8, 1], [9, 4]],  # enrollment.student_id->student, course_id->course
    },
    {
        "db_id": "pets_1",
        "table_names_original": ["owner", "pet"],
        "table_names": ["owner", "pet"],
        "column_names_original": [
            [-1, "*"],
            [0, "owner_id"], [0, "owner_name"], [0, "city"],   # 1,2,3
            [1, "pet_id"], [1, "owner_id"], [1, "species"], [1, "age"],  # 4,5,6,7
        ],
        "column_names": [
            [-1, "*"],
            [0, "owner id"], [0, "owner name"], [0, "city"],
            [1, "pet id"], [1, "owner id"], [1, "species"], [1, "age"],
        ],
        "column_types": ["text", "number", "text", "text", "number", "number", "text", "number"],
        "primary_keys": [1, 4],
        "foreign_keys": [[5, 1]],  # pet.owner_id -> owner.owner_id
    },
]

# ---------------------------------------------------------------------------
#  dev.json — Spider examples. We include the fields our pipeline reads
#  (db_id, question, query). The full Spider file also has query_toks,
#  question_toks, and a parsed `sql` dict; those are omitted here because our
#  Week-1 code doesn't consume them. Spread across complexity tiers.
# ---------------------------------------------------------------------------
EXAMPLES = [
    {"db_id": "college_1", "question": "List all student names.",
     "query": "SELECT name FROM student"},
    {"db_id": "college_1", "question": "How many students have a GPA above 3.5?",
     "query": "SELECT count(*) FROM student WHERE gpa > 3.5"},
    {"db_id": "college_1", "question": "Show each student's name and the title of courses they are enrolled in.",
     "query": "SELECT s.name, c.title FROM enrollment e JOIN student s ON e.student_id = s.student_id JOIN course c ON e.course_id = c.course_id"},
    {"db_id": "college_1", "question": "What is the average GPA per course title?",
     "query": "SELECT c.title, avg(s.gpa) FROM enrollment e JOIN student s ON e.student_id = s.student_id JOIN course c ON e.course_id = c.course_id GROUP BY c.title HAVING count(*) > 1"},
    {"db_id": "college_1", "question": "Which students have a GPA higher than the average GPA?",
     "query": "SELECT name FROM student WHERE gpa > (SELECT avg(gpa) FROM student)"},
    {"db_id": "pets_1", "question": "List all pet species.",
     "query": "SELECT DISTINCT species FROM pet"},
    {"db_id": "pets_1", "question": "How many pets does each owner have?",
     "query": "SELECT o.owner_name, count(*) FROM owner o JOIN pet p ON p.owner_id = o.owner_id GROUP BY o.owner_name"},
    {"db_id": "pets_1", "question": "Rank pets by age within each species.",
     "query": "SELECT pet_id, species, age, rank() OVER (PARTITION BY species ORDER BY age DESC) AS age_rank FROM pet"},
]

# ---------------------------------------------------------------------------
#  SQLite database contents (one .sqlite file per db_id, like real Spider).
# ---------------------------------------------------------------------------
DDL = {
    "college_1": [
        "CREATE TABLE student (student_id INTEGER PRIMARY KEY, name TEXT NOT NULL, gpa REAL)",
        "CREATE TABLE course (course_id INTEGER PRIMARY KEY, title TEXT NOT NULL, credits INTEGER)",
        ("CREATE TABLE enrollment (enroll_id INTEGER PRIMARY KEY, student_id INTEGER, "
         "course_id INTEGER, grade TEXT, "
         "FOREIGN KEY(student_id) REFERENCES student(student_id), "
         "FOREIGN KEY(course_id) REFERENCES course(course_id))"),
    ],
    "pets_1": [
        "CREATE TABLE owner (owner_id INTEGER PRIMARY KEY, owner_name TEXT NOT NULL, city TEXT)",
        ("CREATE TABLE pet (pet_id INTEGER PRIMARY KEY, owner_id INTEGER, species TEXT, age INTEGER, "
         "FOREIGN KEY(owner_id) REFERENCES owner(owner_id))"),
    ],
}
ROWS = {
    "college_1": {
        "student": [(1, "Alice", 3.9), (2, "Bob", 3.2), (3, "Carol", 3.7), (4, "Dan", 2.8)],
        "course": [(1, "Databases", 3), (2, "Algorithms", 4), (3, "Calculus", 3)],
        "enrollment": [
            (1, 1, 1, "A"), (2, 1, 2, "A"), (3, 2, 1, "B"),
            (4, 3, 2, "A"), (5, 3, 3, "B"), (6, 4, 3, "C"),
        ],
    },
    "pets_1": {
        "owner": [(1, "Eve", "Sewanee"), (2, "Frank", "Nashville")],
        "pet": [(1, 1, "cat", 3), (2, 1, "dog", 5), (3, 2, "cat", 2), (4, 2, "dog", 7)],
    },
}


def build_sqlite(db_id: str, db_dir: Path) -> None:
    db_dir.mkdir(parents=True, exist_ok=True)
    path = db_dir / f"{db_id}.sqlite"
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        for stmt in DDL[db_id]:
            cur.execute(stmt)
        for table, rows in ROWS[db_id].items():
            placeholders = ",".join("?" * len(rows[0]))
            cur.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
        conn.commit()
    finally:
        conn.close()
    print(f"   built {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="data/spider_sample",
                    help="output dir (default: data/spider_sample)")
    args = ap.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    (dest / "tables.json").write_text(json.dumps(TABLES, indent=2))
    (dest / "dev.json").write_text(json.dumps(EXAMPLES, indent=2))
    print(f"==> wrote {dest/'tables.json'} ({len(TABLES)} databases)")
    print(f"==> wrote {dest/'dev.json'} ({len(EXAMPLES)} examples)")

    for db_id in DDL:
        build_sqlite(db_id, dest / "database" / db_id)

    print(f"==> sample dataset ready at {dest}/")


if __name__ == "__main__":
    main()
