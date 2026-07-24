# Text-to-SQL Platform with LLM Benchmarking

> Convert natural-language questions into executable SQL, benchmark which prompting strategy produces the most accurate queries, and repair failures with a RAG-based self-correction pipeline.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Benchmark](https://img.shields.io/badge/Spider%20dev-1034%20questions-brightgreen)

**SURF 2026 research project — Sewanee, advised by Dr. Stephen Carl.**

---

## Table of Contents

- [Overview](#overview)
- [Results](#results)
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
2. **Automated benchmarking engine** — evaluates each prompt strategy across query-complexity tiers on the [Spider benchmark](https://yale-lily.github.io/spider), measuring execution accuracy and API cost.
3. **RAG-based self-correction pipeline** — when a query fails, retrieves relevant schema context and similar solved examples from a vector store, then re-prompts the model to repair it, measuring the accuracy gain.

---

## Results

### The four prompt strategies

All four receive the same question and differ only in what context they supply. A "shot" is a worked example, so zero-shot means zero examples provided.

| Strategy | What the prompt contains |
|----------|--------------------------|
| **zero-shot** | Table and column names only. No types, keys, or sample rows, and no worked examples. Tests how well the model does with minimal context. |
| **schema-aware** | Full `CREATE TABLE` DDL with column types, primary keys, and foreign keys, plus a few sample rows from each table. Tests how much richer schema detail helps. |
| **few-shot** | The same full DDL, preceded by two generic worked question-to-SQL example pairs. Tests whether demonstrating the expected output format helps. |
| **chain-of-thought** | The same full DDL, with an instruction to reason step by step (identify tables, joins, filters) before writing the query. Tests whether explicit reasoning helps, at the cost of extra output tokens. |

Every strategy shares the same output rules, including the instruction to select only the columns the question asks for, so the context each supplies is the only variable.

Full Spider dev set, all four prompt strategies, Claude Haiku 4.5. Of 1,034 dev questions, 150 (14.5%) have gold queries that do not execute on PostgreSQL and are excluded, leaving **884 scored questions per strategy**. Total API cost for the complete run: **$4.34**.

| Strategy | Accuracy | Correct | Cost | Cost / correct answer |
|----------|---------:|--------:|-----:|----------------------:|
| few-shot | **79.5%** | 703/884 | $1.01 | $0.00144 |
| schema-aware | **79.4%** | 702/884 | $1.01 | $0.00144 |
| chain-of-thought | 76.5% | 676/884 | $1.94 | $0.00287 |
| zero-shot | 72.6% | 642/884 | $0.38 | $0.00059 |

### Accuracy by official Spider hardness

| Strategy | easy (n=214) | medium (n=376) | hard (n=158) | extra (n=136) |
|----------|-------------:|---------------:|-------------:|--------------:|
| zero-shot | 91.1% | 71.8% | 71.5% | 47.1% |
| schema-aware | 91.6% | **80.6%** | 75.9% | **61.0%** |
| few-shot | **94.4%** | 79.8% | 75.9% | 59.6% |
| chain-of-thought | 89.7% | 76.6% | **79.1%** | 52.2% |

### Findings

**The schema-context advantage widens with query difficulty.** Measured against zero-shot, schema-aware gains roughly 0.5 points on easy, 8.8 on medium, 4.4 on hard, and 13.9 on extra-hard. Simple queries do not require foreign-key information; nested multi-table queries do. This is the project's central hypothesis, supported on the full dev set.

**This corrects an earlier small-sample conclusion.** On an 82-question sample the extra-hard collapse appeared uniform across all four strategies. With 136 extra-hard questions it clearly is not: schema-aware holds 61.0% where zero-shot falls to 47.1%. The smaller sample produced a confident but incorrect conclusion.

**Chain-of-thought is strictly dominated.** Lower accuracy than schema-aware (76.5% vs 79.4%, a 26-question gap) at roughly double the cost. No accuracy or budget regime favours it. It does lead on the hard tier (79.1%) while being worst on easy (89.7%), consistent with an overthinking pattern, but that lead is only 5 questions and is treated as a hypothesis rather than a finding.

**Few-shot and schema-aware are statistically indistinguishable** (703 vs 702 of 884, a one-question difference).

**Zero-shot is a real cost option.** It delivers 91% of schema-aware's accuracy at 38% of its cost, which matters at scale.

Reproduce with `python scripts/run_full_benchmark.py`. Raw per-question results are written to `benchmarks/results/full_dev_comparison.json`.

---

## Current Status

The generation, execution, scoring, and benchmarking pipeline is complete and has been run over the full Spider dev set. Prompt strategy comparison and per-difficulty analysis are finished.

Remaining work: the **RAG self-correction pipeline**. The extra-hard tier (61.0% at best) is where retrieval and retry has the most headroom to demonstrate a measurable gain.

---

## Architecture

The pipeline runs top to bottom. `[done]` stages are implemented; `[planned]` stages remain.

```
question + target database
            |
            v
  Schema Introspector ........... [done]
  Prompt Builder + LLM Router ... [done]
  SQL Cleanup ................... [done]
  Read-only Execution Sandbox ... [done]
  Scorer (execution accuracy) ... [done]
  Benchmark Engine + Analysis ... [done]
            |
            v
  RAG Self-Correction Loop ...... [planned]
            |
            v
     scored benchmark results
```

**Stages.**

- The *Schema Introspector* reads the target database's tables, columns, and keys and renders them for the prompt.
- The *Prompt Builder + LLM Router* wraps that schema under one of four strategies and calls the model, tracking token cost.
- *SQL Cleanup* strips markdown fences from the output.
- The *Execution Sandbox* runs the query as a read-only role with a statement timeout.
- The *Scorer* normalizes the gold query's SQLite dialect, executes both queries, and compares result sets by execution match.
- The *Benchmark Engine* runs the full dev set with checkpointing and resume, and reports accuracy per strategy and per Spider hardness tier.
- The *RAG self-correction loop* is the remaining milestone.

---

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| Backend | Python 3.12, FastAPI, Pydantic |
| Database | PostgreSQL 16, psycopg 3 |
| Infrastructure | Docker, Docker Compose |
| LLM providers | Anthropic Claude (implemented); OpenAI, Google Gemini, Ollama (planned) |
| RAG | ChromaDB, Sentence-Transformers (planned) |
| Frontend | React (planned) |
| Tooling | pytest, Ruff, Make |

---

## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Python 3.12 (3.13+ lacks prebuilt wheels for several pinned dependencies)
- An Anthropic API key

### Installation

```bash
git clone <your-repo-url> text-to-sql && cd text-to-sql
cp .env.example .env          # set database passwords and ANTHROPIC_API_KEY

# start PostgreSQL (creates the spider + metadata DBs and the read-only role)
docker compose up -d db

# set up the Python environment
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Loading Data

```bash
# Option A — tiny synthetic sample (no download required)
make sample        # generates data/spider_sample/
make explore       # prints dataset stats + complexity distribution
make load          # loads the sample into PostgreSQL

# Option B — the full Spider dataset
bash scripts/download_spider.sh                 # follow printed instructions
python scripts/explore_spider.py --data-dir data/spider

# load only the ~20 databases the dev set references
python scripts/load_spider.py --data-dir data/spider --db-ids-from data/spider/dev.json
```

### Running the Benchmark

```bash
python scripts/test_llm.py             # single Claude call; prints cost
python scripts/test_pipeline.py        # generate -> execute -> score on the sample
python scripts/benchmark_dev.py        # 100-question sample, one strategy
python scripts/run_full_benchmark.py   # full dev set, all strategies (~45 min, ~$4.34)
```

The full benchmark checkpoints every 25 questions to `benchmarks/results/full_dev_comparison.json` and resumes from saved state if interrupted. Prefix with `caffeinate -i` on macOS to prevent sleep during the run.

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
│   │   └── scorer.py              # execution-match scoring vs gold
│   ├── prompts/strategies.py      # zero-shot / schema-aware / few-shot / chain-of-thought
│   ├── utils/
│   │   ├── complexity.py          # SQL -> 5-tier complexity classifier
│   │   ├── spider_hardness.py     # official Spider easy/medium/hard/extra tiers
│   │   ├── sql_dialect.py         # normalize SQLite-dialect gold SQL for PostgreSQL
│   │   └── sql_extract.py         # strip markdown fences from LLM output
│   └── routers/                   # API endpoints (planned)
├── scripts/
│   ├── download_spider.sh         # fetch the real Spider dataset
│   ├── make_sample_spider.py      # generate a faithful tiny sample
│   ├── explore_spider.py          # dataset stats + complexity report
│   ├── load_spider.py             # SQLite -> PostgreSQL loader (data-driven type inference)
│   ├── test_llm.py                # single-call smoke test (cost check)
│   ├── test_text_to_sql.py        # end-to-end generation on the sample
│   ├── test_pipeline.py           # generate + execute + score
│   ├── benchmark_dev.py           # sampled dev-set benchmark, one strategy
│   ├── compare_strategies.py      # sampled benchmark, all four strategies
│   └── run_full_benchmark.py      # full dev set, checkpointed and resumable
├── docker/postgres-init/          # one-time DB + role initialization
├── tests/                         # classifier + introspector tests
├── data/                          # datasets (gitignored; downloaded/generated)
├── benchmarks/results/            # benchmark output JSON
├── frontend/                      # React app (planned)
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

- **One PostgreSQL instance, many schemas.** Each Spider `db_id` becomes a schema inside the `spider` database, which is lighter on a laptop than many separate databases. App data lives in a separate `metadata` database.
- **Read-only executor role.** The `query_executor` role can only `SELECT`. The sandboxed executor connects as this role, so generated SQL can never mutate data (write-block verified: `DELETE` returns permission denied).
- **Column types inferred from data, not declarations.** SQLite's declared types are unreliable in Spider: the same ID column may be declared `TEXT` in one table and `INTEGER` in another, which breaks joins on PostgreSQL. The loader reads each column's actual values and picks `BIGINT`, `DOUBLE PRECISION`, or `TEXT` accordingly, with a guard to keep zero-padded codes as text.
- **Sanitized identifiers on load.** Identifiers are lowercased and sanitized so LLM-generated, unquoted SQL executes against the loaded schemas.
- **Prompt strategy as the research variable.** Four strategies are benchmarked under identical conditions on identical questions to isolate the effect of prompt design.
- **Shared output rules across strategies.** The instruction to select only the columns the question asks for lives in the shared system prompt, so strategies differ only in the context they supply. Adding it lifted all four strategies by 2.4 to 3.7 points.
- **Execution-match scoring.** Correctness is measured by executing both queries and comparing result sets: column order is ignored, row order matters only when the gold query has `ORDER BY`, and numeric values are normalized so `3`, `3.0`, and `"3"` compare equal.
- **Gold queries are pre-validated before generation.** The full benchmark executes every gold query against the database first, then skips generation for the unscoreable ones. This saves roughly 15% of API calls.
- **Official Spider hardness tiers.** `eval_hardness` is reimplemented from Spider's `evaluation.py`, reading the parsed `sql` dict shipped with each dev example, so accuracy is reported in the same buckets as published Spider results.

---

## Known Limitations

- **14.5% of Spider's dev gold queries do not execute on PostgreSQL** (150 of 1,034). Causes: double-quoted string literals (SQLite reads these as strings, PostgreSQL as identifiers), aggregates over text columns such as `avg(transcript_date)`, and selection of non-grouped columns under PostgreSQL's stricter `GROUP BY` rules. These are reported and excluded rather than counted against the model. A preprocessor recovers the double-quote cases; the rest are inherent to running Spider outside SQLite.
- **Execution match, not test-suite accuracy.** This is a faithful reimplementation of execution-match accuracy on PostgreSQL, not Spider's full test-suite accuracy, which runs each query against multiple distilled database instances to catch false positives. That remains future work.
- **Single model.** All results are Claude Haiku 4.5. The multi-LLM axis of the research question is not yet addressed.
- **Some gold queries are themselves questionable.** Several scored failures are cases where the generated query is arguably more correct than the gold, for example using `DISTINCT` where the gold's join emits duplicate rows.
- The loader maps column types but not `NOT NULL` / `CHECK` constraints from SQLite. Acceptable for read-only benchmarking.
- Spider's hosting changes over time; confirm the current link at <https://yale-lily.github.io/spider>.

---

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Project scaffold, Dockerized PostgreSQL, Spider tooling, schema introspector | Done |
| 2 | Four prompt strategies + cost-tracked LLM router | Done |
| 3 | Read-only SQL execution sandbox + execution-match scoring | Done |
| 4 | Full Spider dataset, official hardness tiers, full dev-set benchmark | Done |
| 5 | RAG self-correction pipeline | In progress |
| 6 | Second LLM for the model x strategy comparison | Planned |
| 7 | React frontend + results dashboard | Planned |
| 8 | Deployment | Planned |
| 9 | Research paper + poster | Planned |

---

## Acknowledgements

- [Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task](https://arxiv.org/abs/1809.08887) (Yu et al., 2018) — Yale LILY Lab.
- Conducted as part of the SURF 2026 / McGriff-Bruton research fellowship, Sewanee: The University of the South.

## License

To be determined — confirm with project advisor before adding an open-source license.