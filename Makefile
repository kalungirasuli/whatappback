.PHONY: install dev lint format test migrate docker-up docker-down

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

lint:
	ruff check src/ tests/
	mypy src/

format:
	ruff format src/ tests/

test:
	pytest -v --cov=src --cov-report=term-missing

migrate:
	alembic upgrade head

docker-up:
	docker compose -f docker/docker-compose.yml up --build -d

docker-down:
	docker compose -f docker/docker-compose.yml down
