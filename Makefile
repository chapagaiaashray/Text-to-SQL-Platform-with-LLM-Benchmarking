.PHONY: help up down logs sample explore load test api fmt

help:
	@echo "make up       - start postgres (docker)"
	@echo "make down     - stop docker services"
	@echo "make sample   - generate the tiny Spider sample dataset"
	@echo "make explore  - explore the sample dataset"
	@echo "make load     - load the sample dataset into postgres"
	@echo "make test     - run the test suite"
	@echo "make api      - run the FastAPI dev server"
	@echo "make fmt      - format/lint with ruff"

up:
	docker compose up -d db

down:
	docker compose down

logs:
	docker compose logs -f db

sample:
	python scripts/make_sample_spider.py

explore:
	python scripts/explore_spider.py --data-dir data/spider_sample

load:
	python scripts/load_spider.py --data-dir data/spider_sample

test:
	PYTHONPATH=. pytest -q

api:
	uvicorn backend.main:app --reload

fmt:
	ruff check --fix . && ruff format .
