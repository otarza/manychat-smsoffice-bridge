.PHONY: help install test lint run deploy clean

help:
	@echo "Available commands:"
	@echo "  make install   Install development dependencies"
	@echo "  make test      Run pytest"
	@echo "  make lint      Run ruff linter"
	@echo "  make run       Run send_sms locally on http://localhost:8080"
	@echo "  make run-cb    Run sms_callback locally on http://localhost:8081"
	@echo "  make deploy    Deploy both functions to GCP"
	@echo "  make clean     Remove caches"

install:
	pip install -r requirements-dev.txt

test:
	python -m pytest tests/ -v

lint:
	ruff check .

run:
	@test -f .env && export $$(grep -v '^#' .env | xargs) && \
		functions-framework --target=send_sms --debug --port=8080

run-cb:
	@test -f .env && export $$(grep -v '^#' .env | xargs) && \
		functions-framework --target=sms_callback --debug --port=8081

deploy:
	./deploy.sh

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ tests/__pycache__
	find . -name "*.pyc" -delete
