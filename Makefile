COMPOSE := docker compose -f infra/docker-compose.yml
DATA    ?= cashflow_dataset_participants/statements
PY      := ml/.venv/bin/python

.PHONY: help gen gen-proto gen-api test test-go test-ml lint up up-bot down logs ml-venv ml-serve backtest export ml-backtest ml-train

help:
	@echo "gen        — код из proto/ и api/openapi.yaml"
	@echo "test       — go test + pytest"
	@echo "lint       — buf lint, go vet, gofmt"
	@echo "up / down  — docker compose (postgres, ml, api, worker)"
	@echo "ml-venv    — локальное окружение для ml/"
	@echo "ml-serve   — ML-сервис локально на :50051"
	@echo "backtest   — бэктест на датасете кейса (ML=localhost:50051 — через ML-сервис)"
	@echo "export     — дневные потоки для обучения в ml/data/flows.csv"
	@echo "ml-backtest — сравнение моделей в Python (MODELS=seasonal_naive,ets,gbm_global)"
	@echo "ml-train   — обучить глобальные модели на всех данных → ml/artifacts"

gen: gen-proto gen-api

# Нужны: buf, protoc-gen-go, protoc-gen-go-grpc (go install ...), ml-venv.
gen-proto:
	buf lint
	buf generate
	$(PY) -m grpc_tools.protoc -I proto --python_out=ml/gen --pyi_out=ml/gen --grpc_python_out=ml/gen proto/forecast/v1/forecaster.proto proto/categorize/v1/categorizer.proto

gen-api:
	cd backend && go generate ./internal/httpapi && ./scripts/gen-unimplemented.sh

test: test-go test-ml

test-go:
	cd backend && go test ./...

test-ml:
	cd ml && .venv/bin/python -m pytest -q

lint:
	buf lint
	cd backend && go vet ./... && test -z "$$(gofmt -l cmd internal)"

up:
	$(COMPOSE) up -d --build

up-bot:
	$(COMPOSE) --profile bot up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api worker ml

ml-venv:
	python3 -m venv ml/.venv
	ml/.venv/bin/pip install -e "ml[dev]"

ml-serve:
	cd ml && PYTHONPATH=gen .venv/bin/python -m zavozik_ml.serving.server

backtest:
	cd backend && go run ./cmd/backtest -data ../$(DATA) -out ../ml/data/backtest.csv $(if $(ML),-ml $(ML))

export:
	cd backend && go run ./cmd/export -data ../$(DATA) -out ../ml/data/flows.csv

MODELS ?= seasonal_naive,ets,gbm_global

ml-backtest: export
	cd ml && PYTHONPATH=gen .venv/bin/python -m zavozik_ml.eval.backtest --models $(MODELS)

ml-train: export
	cd ml && PYTHONPATH=gen .venv/bin/python -m zavozik_ml.train
