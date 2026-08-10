.PHONY: help up down extract status export test lint clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

up:  ## Start Memgraph + Lab containers
	docker compose up -d

down:  ## Stop containers
	docker compose down

extract:  ## Run extraction pipeline (REPO=path required)
	uv run pipeline extract --repo $(REPO)

status:  ## Show graph database statistics
	uv run pipeline status

export:  ## Export graph (PROJECT=name required)
	uv run pipeline export --format cypherl --output ./graph_export/$(PROJECT)/

test:  ## Run test suite
	uv run pytest

lint:  ## Run ruff linter
	uv run ruff check src/ tests/

clean:  ## Remove cache files
	rm -rf .cache/ __pycache__ .pytest_cache
