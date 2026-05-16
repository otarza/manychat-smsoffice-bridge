PROJECT_ID ?= $(shell gcloud config get-value project 2>/dev/null)
REGION ?= europe-west1

LOG_FILTER_ALL = resource.type="cloud_run_revision" AND (resource.labels.service_name="send-sms" OR resource.labels.service_name="sms-callback")
LOG_FILTER_SEND_RESULTS = resource.type="cloud_run_revision" AND resource.labels.service_name="send-sms" AND jsonPayload.event="send_result"
LOG_FILTER_SEND_FAILURES = resource.type="cloud_run_revision" AND resource.labels.service_name="send-sms" AND (jsonPayload.event="send_exception" OR jsonPayload.event="send_validation_failed" OR jsonPayload.success=false)
LOG_FORMAT_RESULTS = table(timestamp,jsonPayload.reference,jsonPayload.destination_masked,jsonPayload.success,jsonPayload.error_code,jsonPayload.message)
LOG_FORMAT_FAILURES = table(timestamp,jsonPayload.event,jsonPayload.reference,jsonPayload.destination_masked,jsonPayload.error,jsonPayload.error_code,jsonPayload.message)

.PHONY: help install test lint run deploy logs-send logs-callback logs-tail logs-broadcast-tail logs-results-tail logs-failures-tail logs-results logs-failures clean

help:
	@echo "Available commands:"
	@echo "  make install   Install development dependencies"
	@echo "  make test      Run pytest"
	@echo "  make lint      Run ruff linter"
	@echo "  make run       Run send_sms locally on http://localhost:8080"
	@echo "  make run-cb    Run sms_callback locally on http://localhost:8081"
	@echo "  make deploy    Deploy both functions to GCP"
	@echo "  make logs-tail Watch live send/callback logs (requires gcloud beta logging tail)"
	@echo "  make logs-broadcast-tail Watch live broadcast send/callback table"
	@echo "  make logs-results-tail Watch live send results table"
	@echo "  make logs-failures-tail Watch live send failures table"
	@echo "  make logs-results Show latest send results"
	@echo "  make logs-failures Show latest send failures"
	@echo "  make clean     Remove caches"

install:
	pip install -r requirements-dev.txt

test:
	python -m pytest tests/ -v

lint:
	python -m ruff check .

run:
	@test -f .env && export $$(grep -v '^#' .env | xargs) && \
		python -m functions_framework --target=send_sms --debug --port=8080

run-cb:
	python -m functions_framework --target=sms_callback --debug --port=8081

deploy:
	./deploy.sh

logs-send:
	gcloud functions logs read send-sms --project="$(PROJECT_ID)" --region="$(REGION)" --gen2 --limit=100

logs-callback:
	gcloud functions logs read sms-callback --project="$(PROJECT_ID)" --region="$(REGION)" --gen2 --limit=100

logs-tail:
	gcloud beta logging tail '$(LOG_FILTER_ALL)' --project="$(PROJECT_ID)"

logs-broadcast-tail:
	python scripts/tail_logs.py --project="$(PROJECT_ID)" --mode=broadcast

logs-results-tail:
	python scripts/tail_logs.py --project="$(PROJECT_ID)" --mode=results

logs-failures-tail:
	python scripts/tail_logs.py --project="$(PROJECT_ID)" --mode=failures

logs-results:
	gcloud logging read '$(LOG_FILTER_SEND_RESULTS)' --project="$(PROJECT_ID)" --limit=100 --format='$(LOG_FORMAT_RESULTS)'

logs-failures:
	gcloud logging read '$(LOG_FILTER_SEND_FAILURES)' --project="$(PROJECT_ID)" --limit=100 --format='$(LOG_FORMAT_FAILURES)'

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ tests/__pycache__
	find . -name "*.pyc" -delete
