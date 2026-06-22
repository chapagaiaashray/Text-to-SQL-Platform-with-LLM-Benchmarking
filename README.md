# Text-to-SQL Platform with LLM Benchmarking

> Convert natural-language questions into executable SQL, benchmark which LLM and prompting strategy produce the most accurate queries, and automatically repair failures with a RAG-based self-correction pipeline.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Status](https://img.shields.io/badge/status-pipeline%20working-brightgreen)

**SURF 2026 research project — Sewanee, advised by Dr. Stephen Carl.**

---

## Table of Contents

- [Overview](#overview)
- [Current Status](#current-status)
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

1. **Text-to-SQL pipeline** — inspects the connected database, builds a prompt under a selected strategy, routes it to an LLM, executes the generated SQL in a read-only sandbox, and scores the result against a gold answer.
2. **Automated benchmarking engine** — evaluates every combination of *LLM x prompt strategy x query-complexity tier* on the [Spider benchmark](https://yale-lily.github.io/spider) (10,000+ questions across 200 databases), measuring execution accuracy, latency, and cost.
3. **RAG-based self-correction pipeline** — when a query fails, retrieves relevant schema context and similar solved examples from a vector store, then re-prompts the model to repair it, measuring the accuracy gain.

---

## Current Status

The end-to-end pipeline is implemented and verified on a synthetic Spider-format sample: a natural-language question is converted to SQL under any of four prompt strategies, executed in a read-only sandbox, and scored against the gold query by execution accuracy. A comparison runner benchmarks all four strategies side by side and reports per-strategy accuracy and API cost.

Next milestone (Week 4): load the full Spider dataset and vendor Spider's official evaluator so results are comparable to published research.

---

## Architecture

The pipeline runs top to bottom. `[done]` stages are implemented; `[planned]` stages are scheduled for Weeks 4–6.

```
question + target database
            |
            v
  Schema Introspector ........... [done]
  Prompt Builder + LLM Router ... [done]
  SQL Cleanup ................... [done]
  Read-only Execution Sandbox ... [done]
  Scorer (execution accuracy) ... [done]
            |
            v
  Benchmark Engine + Analysis ... [planned]
  RAG Self-Correction Loop ...... [planned]
            |
            v
     scored benchmark results
```

**Stages.** 

- The *Schema Introspector* reads the target database's tables, columns, and keys and renders them for the prompt. The *Prompt Builder + LLM Router* wraps that schema under one of four strategies and calls the model, tracking token cost. 

- *SQL Cleanup* strips markdown fences from the output. 

- The *Execution Sandbox* runs the query as a read-only role with a timeout. 

- The *Scorer* compares the result against the gold query (execution accuracy). 

- The *Benchmark Engine* and *RAG self-correction loop* are the next milestones.
---

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| Backend | Python 3.12, FastAPI, Pydantic |
| Database | PostgreSQL 16, psycopg 3 |
| Infrastructure | Docker, Docker Compose |
| LLM providers | Anthropic Claude (implemented); OpenAI, Google Gemini, Ollama (planned) |
| RAG | ChromaDB, Sentence-Transformers (planned) |
| Frontend | React (Weeks 7-8) |
| Tooling | pytest, Ruff, Make |

---

## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Python 3.12+
- An Anthropic API key (for the generation pipeline)

### Installation

```bash
git clone <your-repo-url> text-to-sql && cd text-to-sql
cp .env.example .env          # set database passwords and ANTHROPIC_API_KEY

# start PostgreSQL (creates the spider + metadata DBs and the read-only role)
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

### Running the Pipeline

```bash
python scripts/test_llm.py             # single Claude call; prints cost
python scripts/test_text_to_sql.py     # question -> SQL on the sample
python scripts/test_pipeline.py        # generate -> execute -> score
python scripts/compare_strategies.py   # benchmark all four strategies
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
│   ├── config.py                  # typed settings + DB connection strings + LLM defaults
│   ├── main.py                    # FastAPI app (health + DB checks)
│   ├── models/schemas.py          # Pydantic models for DB structure
│   ├── services/
│   │   ├── schema_introspector.py # reads any PostgreSQL DB's structure
│   │   ├── llm_router.py          # sends prompts to Claude; tracks tokens + cost
│   │   ├── sql_generator.py       # introspector + strategy + router -> SQL
│   │   ├── sql_executor.py        # runs SQL in a read-only sandbox
│   │   └── scorer.py              # execution-accuracy scoring vs gold
│   ├── prompts/strategies.py      # zero-shot / schema-aware / few-shot / chain-of-thought
│   ├── utils/
│   │   ├── complexity.py          # SQL -> 5-tier complexity classifier
│   │   └── sql_extract.py         # strip markdown fences from LLM output
│   └── routers/                   # API endpoints (later weeks)
├── scripts/
│   ├── download_spider.sh         # fetch the real Spider dataset
│   ├── make_sample_spider.py      # generate a faithful tiny sample
│   ├── explore_spider.py          # dataset stats + complexity report
│   ├── load_spider.py             # SQLite -> PostgreSQL loader
│   ├── test_llm.py                # single-call smoke test (cost check)
│   ├── test_text_to_sql.py        # end-to-end generation on the sample
│   ├── test_pipeline.py           # generate + execute + score
│   └── compare_strategies.py      # benchmark all four strategies
├── docker/postgres-init/          # one-time DB + role initialization
├── tests/                         # classifier + introspector tests
├── data/                          # datasets (gitignored; downloaded/generated)
├── benchmarks/                    # results + analysis (later weeks)
├── frontend/                      # React app (Weeks 7-8)
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
- **Read-only executor role.** The `query_executor` role can only `SELECT`. The sandboxed executor connects as this role, so generated SQL can never mutate data (write-block verified: `DELETE` returns permission denied).
- **Sanitized identifiers on load.** Identifiers are lowercased and sanitized so LLM-generated, unquoted SQL executes against the loaded schemas.
- **Prompt strategy as the research variable.** Four strategies (zero-shot, schema-aware, few-shot, chain-of-thought) are benchmarked under identical conditions to isolate the effect of prompt design.
- **Cost-tracked LLM router.** Every call reports input/output tokens and estimated USD cost. The default model is Claude Haiku for economy; higher tiers are reserved for targeted comparison.
- **Execution-accuracy scoring.** Correctness is measured by running the generated and gold queries and comparing result sets, rather than by string-matching SQL.
- **Project-defined complexity tiers.** Spider's easy/medium/hard/extra labels are *computed* by its `evaluation.py`, not stored in the data. This project uses its own transparent 5-tier classifier; Spider's official evaluator will be vendored in Week 4 for paper-comparable numbers.

---

## Known Limitations

- The scorer uses a simple result-set comparison and penalizes cosmetic differences (extra columns, column ordering). Spider's official evaluator will be vendored in Week 4 for rigorous, paper-comparable scoring.
- Only Anthropic Claude is currently wired into the router; OpenAI, Gemini, and Ollama are planned to complete the multi-LLM comparison.
- The pipeline currently runs against a synthetic two-database sample; the full Spider dataset is not yet loaded.
- The loader maps column **types** but not `NOT NULL` / `CHECK` constraints from SQLite. Acceptable for read-only benchmarking.
- Spider's hosting (Google Drive / Hugging Face) changes over time — confirm the current link at <https://yale-lily.github.io/spider>.

---

## Roadmap

| Week | Focus | Status |
|------|-------|--------|
| 1 | Project scaffold, Dockerized PostgreSQL, Spider tooling, schema introspector | Done |
| 2 | Four prompt strategies + cost-tracked LLM router | Done |
| 3 | Read-only SQL execution sandbox + execution-accuracy scoring | Done |
| 4-5 | Full Spider dataset, official evaluator, automated benchmarking + analysis | In progress |
| 6 | RAG self-correction pipeline | Planned |
| 7-8 | React frontend + results dashboard | Planned |
| 9 | Deployment | Planned |
| 10 | Research paper + poster | Planned |

---

## Acknowledgements

- [Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task](https://arxiv.org/abs/1809.08887) (Yu et al., 2018) — Yale LILY Lab.
- Conducted as part of the SURF 2026 / McGriff-Bruton research fellowship, Sewanee: The University of the South.

## License

To be determined — confirm with project advisor before adding an open-source license.