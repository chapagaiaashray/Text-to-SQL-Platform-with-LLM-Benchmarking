# Text-to-SQL Platform with LLM Benchmarking

> Convert natural-language questions into executable SQL and measure which prompting strategies actually improve accuracy on Yale's Spider benchmark.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Benchmark](https://img.shields.io/badge/Spider%20dev-1034%20questions-blue)
![Status](https://img.shields.io/badge/status-complete-brightgreen)

**SURF 2026 research project — Sewanee, advised by Dr. Stephen Carl. Completed August 2026.**

---

## Table of Contents

- [Overview](#overview)
- [Headline Finding](#headline-finding)
- [Results](#results)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Design Decisions](#design-decisions)
- [Known Limitations](#known-limitations)
- [Future Work](#future-work)
- [Acknowledgements](#acknowledgements)
- [License](#license)

---

## Overview

This project asks: **how far can prompt design alone push an off-the-shelf LLM toward accurate text-to-SQL, without fine-tuning?**

It has three parts:

1. **Text-to-SQL pipeline** — introspects the connected database, builds a prompt under a selected strategy, routes it to an LLM, executes the generated SQL in a read-only sandbox, and scores the result against a gold answer by execution match.
2. **Automated benchmarking engine** — evaluates six prompting strategies across Spider's official difficulty tiers, measuring execution accuracy and API cost, with checkpointing and resume for long runs.
3. **Retrieval-augmented generation** — indexes Spider's 7,000 training queries in a vector store and supplies semantically similar solved examples at generation time, tested both unfiltered and with a retrieval-quality threshold.

Part 3 was originally scoped as RAG-based *self-correction* (retrieve and retry after a query fails). A failure-mode diagnostic showed only 10.7% of failures produce an execution error a production system could detect, so retrieval was moved from after-failure to before-generation. See [Design Decisions](#design-decisions).

---

## Headline Finding

**Schema context is worth about seven points. Examples are worth nothing.**

Moving from bare column names (zero-shot, 72.6%) to full DDL with keys and sample rows (schema-aware, 79.4%) gains 60 questions out of 884. Adding examples on top of that — generic, semantically retrieved, or quality-filtered — moves the total by between −2 and +1 question.

The model needs to know what the database looks like. It does not need to be shown how someone else wrote a query.

---

## Results

### The six strategies

All six receive the same question and differ only in what context the prompt supplies. A "shot" is a worked example, so zero-shot means zero examples.

| Strategy | What the prompt contains |
|----------|--------------------------|
| **zero-shot** | Table and column names only. No types, keys, sample rows, or examples. |
| **schema-aware** | Full `CREATE TABLE` DDL with column types, primary and foreign keys, plus a few sample rows per table. |
| **few-shot** | The same full DDL, preceded by two generic hardcoded question-to-SQL example pairs. |
| **chain-of-thought** | The same full DDL, with an instruction to reason step by step (identify tables, joins, filters) before writing the query. |
| **rag_few_shot** | The same full DDL, preceded by the three most semantically similar questions retrieved from Spider's *training* split, shown with their gold SQL. |
| **rag_adaptive** | As above, but retrieved examples are discarded when the top-1 embedding distance exceeds 0.6, falling back to schema-only prompting. |

Every strategy shares the same output rules, including the instruction to select only the columns the question asks for, so the supplied context is the only variable.

### Full dev set

Claude Haiku 4.5. Of 1,034 dev questions, 150 (14.5%) have gold queries that do not execute on PostgreSQL and are excluded, leaving **884 scored questions per strategy**.

| Strategy | Accuracy | Correct | Cost | Cost / correct |
|----------|---------:|--------:|-----:|---------------:|
| few-shot | **79.5%** | 703/884 | $1.01 | $0.00144 |
| rag_few_shot | **79.5%** | 703/884 | $1.11 | $0.00158 |
| schema-aware | 79.4% | 702/884 | $1.01 | $0.00144 |
| rag_adaptive | 79.2% | 700/884 | $1.02 | $0.00146 |
| chain-of-thought | 76.5% | 676/884 | $1.94 | $0.00287 |
| zero-shot | 72.6% | 642/884 | $0.38 | $0.00059 |

### Accuracy by official Spider hardness

| Strategy | easy (n=214) | medium (n=376) | hard (n=158) | extra (n=136) |
|----------|-------------:|---------------:|-------------:|--------------:|
| zero-shot | 91.1% | 71.8% | 71.5% | 47.1% |
| schema-aware | 91.6% | **80.6%** | 75.9% | **61.0%** |
| few-shot | **94.4%** | 79.8% | 75.9% | 59.6% |
| chain-of-thought | 89.7% | 76.6% | **79.1%** | 52.2% |
| rag_few_shot | 89.7% | **82.7%** | **77.2%** | 57.4% |
| rag_adaptive | 91.6% | 81.6% | 74.7% | 58.1% |

### Findings

**1. The schema-context advantage widens with query difficulty.** Against zero-shot, schema-aware gains roughly 0.5 points on easy, 8.8 on medium, 4.4 on hard, and 13.9 on extra-hard. Simple queries touch one table and need no foreign-key information; nested multi-table queries cannot be written without it.

**2. Retrieval redistributes accuracy rather than raising it.** Against generic few-shot, retrieved examples gained 11 questions on medium and 2 on hard but lost 10 on easy and 3 on extra-hard, for a net of zero at 10% higher cost. On easy questions the model already succeeds, and examples drawn from unrelated databases act as a distraction.

**3. Filtering by retrieval quality confirms that mechanism but nets zero.** Discarding weak retrievals recovered the easy-tier losses exactly (196/214, matching schema-aware) and gave back the medium-tier gain in the process. Retrieval distance also proved nearly flat across difficulty tiers (median 0.720–0.765), so it cannot distinguish questions that need help from questions that do not.

**4. Chain-of-thought is strictly dominated.** Lower accuracy than schema-aware (a 26-question gap) at roughly double the cost. No accuracy or budget regime favours it. It does lead on the hard tier while being worst on easy, consistent with an overthinking pattern, but that lead is only 5 questions and is treated as a hypothesis.

**5. Zero-shot is a real cost option.** It delivers 91% of schema-aware's accuracy at 38% of its cost, which matters at scale.

**6. Small samples repeatedly produced confident wrong conclusions.** An 82-question sample, a 100-question sample, and a 200-question RAG pilot each supported a conclusion the full 884-question set overturned. The 200-question pilot showed retrieval ahead by 3.4 points; on the full set the gain vanished entirely. Recorded as a methodological finding in its own right.

Reproduce with `python scripts/run_full_benchmark.py`. Raw per-question results are in `benchmarks/results/`.

---

## Architecture

```
question + target database
            |
            v
  Schema Introspector ........... [done]
  Example Retriever (optional) .. [done]
  Prompt Builder + LLM Router ... [done]
  SQL Cleanup ................... [done]
  Read-only Execution Sandbox ... [done]
  Scorer (execution match) ...... [done]
  Benchmark Engine + Analysis ... [done]
            |
            v
     scored benchmark results
```

**Stages.**

- The *Schema Introspector* reads the target database's tables, columns, types, and keys and renders them as prompt-ready DDL with sample rows.
- The *Example Retriever* embeds the incoming question and returns the nearest training questions with their gold SQL. Used only by the two RAG strategies.
- The *Prompt Builder + LLM Router* assembles the prompt under the selected strategy and calls the model, reporting token usage and USD cost per call.
- *SQL Cleanup* strips markdown code fences from the model's output.
- The *Execution Sandbox* runs the query as a read-only role with the session `search_path` set to the target schema and a statement timeout.
- The *Scorer* normalizes the gold query's SQLite dialect, executes both queries, and compares result sets by execution match.
- The *Benchmark Engine* runs the full dev set with checkpointing and resume, reporting accuracy per strategy and per Spider hardness tier.

---

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| Backend | Python 3.12, FastAPI, Pydantic |
| Database | PostgreSQL 16, psycopg 3 |
| Infrastructure | Docker, Docker Compose |
| LLM provider | Anthropic Claude (Haiku 4.5) |
| Retrieval | ChromaDB, sentence-transformers (`all-MiniLM-L6-v2`) |
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
make sample && make explore && make load

# Option B — the full Spider dataset
bash scripts/download_spider.sh                 # follow printed instructions
python scripts/explore_spider.py --data-dir data/spider

# load only the ~20 databases the dev set references
python scripts/load_spider.py --data-dir data/spider --db-ids-from data/spider/dev.json

# build the retrieval index (local embeddings, no API cost, ~10 seconds)
python scripts/build_rag_index.py
```

### Running the Benchmarks

```bash
python scripts/test_llm.py                # single Claude call; prints cost
python scripts/test_pipeline.py           # generate -> execute -> score on the sample
python scripts/benchmark_dev.py           # 100-question sample, one strategy
python scripts/benchmark_rag.py           # RAG vs few-shot vs schema-aware, 200 questions
python scripts/run_full_benchmark.py      # full dev set, all strategies (~45 min, ~$4.34)
python scripts/run_adaptive_benchmark.py  # full dev set, distance-thresholded retrieval
```

Analysis utilities (no API cost beyond the first):

```bash
python scripts/analyze_failures.py        # execution errors vs silent wrong results
python scripts/analyze_distances.py       # retrieval distance by difficulty tier
python scripts/check_distance_effect.py   # accuracy by retrieval distance bucket
```

Long runs checkpoint every 25 questions and resume from saved state if interrupted. Prefix with `caffeinate -i` on macOS to prevent sleep.

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
│   │   ├── retriever.py           # nearest training questions from ChromaDB
│   │   ├── llm_router.py          # sends prompts to Claude; tracks tokens + cost
│   │   ├── sql_generator.py       # introspector + retriever + strategy + router -> SQL
│   │   ├── sql_executor.py        # runs SQL in a read-only sandbox
│   │   └── scorer.py              # execution-match scoring vs gold
│   ├── prompts/strategies.py      # the six prompting strategies
│   ├── utils/
│   │   ├── complexity.py          # SQL -> 5-tier complexity classifier
│   │   ├── spider_hardness.py     # official Spider easy/medium/hard/extra tiers
│   │   ├── sql_dialect.py         # normalize SQLite-dialect gold SQL for PostgreSQL
│   │   └── sql_extract.py         # strip markdown fences from LLM output
│   └── routers/                   # API endpoints (not built)
├── scripts/
│   ├── download_spider.sh         # fetch the real Spider dataset
│   ├── make_sample_spider.py      # generate a faithful tiny sample
│   ├── explore_spider.py          # dataset stats + complexity report
│   ├── load_spider.py             # SQLite -> PostgreSQL loader (data-driven type inference)
│   ├── build_rag_index.py         # embed + index the 7,000 training questions
│   ├── test_llm.py                # single-call smoke test (cost check)
│   ├── test_text_to_sql.py        # end-to-end generation on the sample
│   ├── test_pipeline.py           # generate + execute + score
│   ├── benchmark_dev.py           # sampled dev-set benchmark, one strategy
│   ├── compare_strategies.py      # sampled benchmark, four strategies
│   ├── benchmark_rag.py           # sampled benchmark, RAG head-to-head
│   ├── run_full_benchmark.py      # full dev set, checkpointed and resumable
│   ├── run_adaptive_benchmark.py  # full dev set, distance-thresholded retrieval
│   ├── analyze_failures.py        # failure-mode diagnostic
│   ├── analyze_distances.py       # retrieval distance distribution
│   └── check_distance_effect.py   # does distance predict correctness?
├── docker/postgres-init/          # one-time DB + role initialization
├── tests/                         # classifier + introspector tests
├── data/                          # datasets (gitignored; downloaded/generated)
├── benchmarks/results/            # benchmark output JSON
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
- **Read-only executor role.** The `query_executor` role can only `SELECT`, so generated SQL can never mutate data (write-block verified: `DELETE` returns permission denied).
- **Column types inferred from data, not declarations.** SQLite's declared types are unreliable in Spider: the same ID column may be declared `TEXT` in one table and `INTEGER` in another, which breaks joins on PostgreSQL. The loader reads each column's actual values and picks `BIGINT`, `DOUBLE PRECISION`, or `TEXT`, with a guard to keep zero-padded codes as text.
- **Prompt strategy as the research variable.** All strategies run on identical questions under identical conditions, differing only in supplied context.
- **Shared output rules across strategies.** The instruction to select only the columns the question asks for lives in the shared system prompt. Adding it lifted all strategies by 2.4 to 3.7 points, confirming it is orthogonal to strategy rather than favouring one.
- **Execution-match scoring.** Correctness is measured by executing both queries and comparing result sets: column order is ignored, row order matters only when the gold query has `ORDER BY`, and numeric values are normalized so `3`, `3.0`, and `"3"` compare equal.
- **Gold queries are pre-validated before generation.** The benchmark executes every gold query first, then skips generation for unscoreable ones, saving roughly 15% of API calls.
- **Official Spider hardness tiers.** `eval_hardness` is reimplemented from Spider's `evaluation.py`, reading the parsed `sql` dict shipped with each dev example, so accuracy is reported in the same buckets as published Spider results. Verified against the published dev distribution.
- **Retrieval indexes only the training split.** Indexing dev would let a question retrieve its own answer.
- **Retrieval before generation, not after failure.** The project was originally scoped around RAG self-correction: detect a failed query, retrieve context, retry. A diagnostic over 150 questions found only 3 execution errors against 25 silent wrong results, so just 10.7% of failures are detectable without the gold answer, and all 3 errors traced to a single loader bug rather than model reasoning. Such a loop would fire on roughly 2% of questions. Triggering on wrong *results* instead was rejected because detecting one requires the gold answer, which no production system has; doing so would inflate the reported gain and describe a system that cannot exist outside a benchmark.

---

## Known Limitations

- **14.5% of Spider's dev gold queries do not execute on PostgreSQL** (150 of 1,034). Causes: double-quoted string literals (SQLite reads these as strings, PostgreSQL as identifiers), aggregates over text columns such as `avg(transcript_date)`, and selection of non-grouped columns under PostgreSQL's stricter `GROUP BY` rules. These are reported and excluded rather than counted against the model. A preprocessor recovers the double-quote cases; the rest are inherent to running Spider outside SQLite.
- **Execution match, not test-suite accuracy.** This is a faithful reimplementation of execution-match accuracy on PostgreSQL, not Spider's test-suite accuracy, which runs each query against multiple distilled database instances to catch false positives. Reported numbers are therefore not directly comparable to published leaderboard figures.
- **Single model.** All results are Claude Haiku 4.5. Whether the schema-context gap narrows on a stronger model is untested and is the most significant open question.
- **General-purpose embeddings.** Retrieval uses sentence embeddings that capture topical rather than SQL-structural similarity. Two questions can be worded alike and need very different queries. A structure-aware retriever was not tested.
- **Some gold queries are themselves questionable.** Several scored failures are cases where the generated query is arguably more correct than the gold, for example using `DISTINCT` where the gold's join emits duplicate rows.
- The loader maps column types but not `NOT NULL` / `CHECK` constraints from SQLite. Acceptable for read-only benchmarking.
- Spider's hosting changes over time; confirm the current link at <https://yale-lily.github.io/spider>.

---

## Future Work

Ordered by expected value:

1. **A second and third model.** The `LLMRouter` was built to swap providers, so this is a configuration change. It would establish whether "schema context matters, examples do not" holds as model capability increases, or is specific to a small model.
2. **A SQL-structure-aware retriever.** Retrieving by query shape (join count, nesting depth, aggregate presence) rather than question wording directly targets the weakness identified in Finding 3.
3. **Spider test-suite accuracy.** Running each query against multiple distilled database instances would make results directly comparable to the published leaderboard.
4. **Web frontend and deployment.** The FastAPI backend exposes health endpoints only; query and benchmark endpoints plus a React dashboard were scoped but not built.

---

## Acknowledgements

- [Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task](https://arxiv.org/abs/1809.08887) (Yu et al., 2018) — Yale LILY Lab.
- Conducted as part of the SURF 2026 / McGriff-Bruton research fellowship, Sewanee: The University of the South.

## License

To be determined — confirm with project advisor before adding an open-source license.