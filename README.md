# Text-to-SQL Platform with LLM Benchmarking

> Convert natural-language questions into executable SQL, benchmark which LLM and prompting strategy produce the most accurate queries, and automatically repair failures with a RAG-based self-correction pipeline.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Status](https://img.shields.io/badge/status-Week%201-orange)

**SURF 2026 research project — Sewanee, advised by Dr. Stephen Carl.**

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Design Decisions](#design-decisions)
- [Known Limitations](#known-limitations)
- [Roadmap](#roadmap)
- [Acknowledgements](#acknowledgements)
- [License](#license)

---

## Overview

This project investigates a research question: **how far can schema-aware prompting and retrieval-augmented self-correction push an off-the-shelf LLM toward accurate text-to-SQL, without fine-tuning?**

It consists of three components:

1. **Text-to-SQL web application** — a user asks a question in plain English; the system inspects the connected database, builds a schema-aware prompt, routes it to a selected LLM, executes the generated SQL in a read-only sandbox, and returns the results.
2. **Automated benchmarking engine** — evaluates every combination of *LLM × prompt strategy × query-complexity tier* on the [Spider benchmark](https://yale-lily.github.io/spider) (10,000+ questions across 200 databases), measuring execution accuracy, latency, and cost.
3. **RAG-based self-correction pipeline** — when a query fails, retrieves relevant schema context and similar solved examples from a vector store, then re-prompts the model to repair it, measuring the accuracy gain.

---

## Architecture

```
  question + target database
        │
        ▼
  ┌──────────────────┐
  │ Schema           │   reads tables, columns, keys, sample rows
  │ Introspector     │   → renders prompt-ready DDL              [✅ Week 1]
  └──────────────────┘
        │
        ▼
  ┌──────────────────┐
  │ Prompt Builder   │   4 strategies: zero-shot, few-shot,
  │ + LLM Router     │   chain-of-thought, schema-aware          [⏳ Week 2]
  └──────────────────┘
        │  generated SQL
        ▼
  ┌──────────────────┐
  │ Read-only        │   query_executor role; cannot mutate data
  │ Execution Sandbox│   (write-block already verified)          [⏳ Week 3]
  └──────────────────┘
        │  results / error
        ▼
  ┌──────────────────┐        ┌──────────────────┐
  │ Benchmark Engine │◀──────▶│ RAG Self-         │
  │ (Spider scoring) │        │ Correction Loop   │
  │      [⏳ Wk 4–5] │        │      [⏳ Week 6]  │
  └──────────────────┘        └──────────────────┘
```

---

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| Backend | Python 3.12, FastAPI, Pydantic |
| Database | PostgreSQL 16, psycopg 3 |
| Infrastructure | Docker, Docker Compose |
| LLM providers | OpenAI, Anthropic, Google Gemini, Ollama (local Llama) |
| RAG | ChromaDB, Sentence-Transformers |
| Frontend | React (Weeks 7–8) |
| Tooling | pytest, Ruff, Make |

---

## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Python 3.12+

### Installation

```bash
git clone <your-repo-url> text-to-sql && cd text-to-sql
cp .env.example .env          # set your database passwords

# start PostgreSQL (creates the `spider` + `metadata` DBs and read-only role)
docker compose up -d db

# set up the Python environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Loading Data

```bash
# Option A — tiny synthetic sample (no download required)
make sample        # generates data/spider_sample/
make explore       # prints dataset stats + complexity distribution
make load          # loads the sample into PostgreSQL

# Option B — the full Spider dataset (~1GB)
bash scripts/download_spider.sh                 # follow printed instructions
python scripts/explore_spider.py --data-dir data/spider
python scripts/load_spider.py   --data-dir data/spider
```

### Running the API

```bash
make api           # or: uvicorn backend.main:app --reload
```

Then visit `http://localhost:8000/health` and `http://localhost:8000/health/db`.

---

## Project Structure

```
text-to-sql/
├── backend/
│   ├── config.py                  # typed settings + DB connection strings
│   ├── main.py                    # FastAPI app (health + DB checks)
│   ├── models/schemas.py          # Pydantic models for DB structure
│   ├── services/
│   │   └── schema_introspector.py # reads any PostgreSQL DB's structure
│   ├── utils/complexity.py        # SQL → 5-tier complexity classifier
│   ├── routers/                   # API endpoints (later weeks)
│   └── prompts/                   # prompt strategies (Week 2)
├── scripts/
│   ├── download_spider.sh         # fetch the real Spider dataset
│   ├── make_sample_spider.py      # generate a faithful tiny sample
│   ├── explore_spider.py          # dataset stats + complexity report
│   └── load_spider.py             # SQLite → PostgreSQL loader
├── docker/postgres-init/          # one-time DB + role initialization
├── tests/                         # classifier + introspector tests
├── data/                          # datasets (gitignored; download/generated)
├── benchmarks/                    # results + analysis (later weeks)
├── frontend/                      # React app (Weeks 7–8)
├── docker-compose.yml
├── Makefile
└── requirements.txt
```

---

## Testing

```bash
make test          # or: PYTHONPATH=. pytest -q
```

The suite covers the SQL complexity classifier (unit tests) and the schema introspector (integration tests against a loaded sample database). Introspector tests skip cleanly when no database is available, so the suite is safe to run in CI.

---

## Design Decisions

- **One PostgreSQL instance, many schemas.** Each Spider `db_id` becomes a schema inside the `spider` database — lighter on a laptop than 200 separate databases. App data lives in a separate `metadata` database.
- **Read-only executor role.** The `query_executor` role can only `SELECT`. The sandboxed executor connects as this role, so generated SQL can never mutate data (write-block verified: `DELETE` → permission denied).
- **Sanitized identifiers on load.** Identifiers are lowercased and sanitized so LLM-generated, unquoted SQL executes against the loaded schemas.
- **Project-defined complexity tiers.** Spider's easy/medium/hard/extra labels are *computed* by its `evaluation.py`, not stored in the data. This project uses its own transparent 5-tier classifier; Spider's official evaluator will be vendored in Week 4 for paper-comparable numbers.

---

## Known Limitations

- The loader maps column **types** but not `NOT NULL` / `CHECK` constraints from SQLite. Acceptable for read-only benchmarking; revisit if needed.
- Spider's hosting (Google Drive / Hugging Face) changes over time — confirm the current link at <https://yale-lily.github.io/spider>.

---

## Roadmap

| Week | Focus | Status |
|------|-------|:------:|
| 1 | Project scaffold, Dockerized PostgreSQL, Spider tooling, schema introspector | ✅ |
| 2 | Prompt strategies + multi-LLM router | ⏳ |
| 3 | Read-only SQL execution sandbox + scoring | ⏳ |
| 4–5 | Automated benchmarking + analysis | ⏳ |
| 6 | RAG self-correction pipeline | ⏳ |
| 7–8 | React frontend + results dashboard | ⏳ |
| 9 | Deployment | ⏳ |
| 10 | Research paper + poster | ⏳ |

---

## Acknowledgements

- [Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task](https://arxiv.org/abs/1809.08887) (Yu et al., 2018) — Yale LILY Lab.
- Conducted as part of the SURF 2026 / McGriff-Bruton research fellowship, Sewanee: The University of the South.

## License

To be determined — confirm with project advisor before adding an open-source license.