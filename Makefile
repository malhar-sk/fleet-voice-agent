# fleet-voice-agent. Run `make help` for targets.
SHELL := /bin/bash
PY ?= .venv/bin/python
DEVICE ?= pi-3
MINUTES ?= 10
COMPOSE ?= docker compose

.PHONY: help up down ps logs chaos recover freeze unfreeze breaches test test-live eval eval-audio examples venv models dashboard n8n-import

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-12s %s\n", $$1, $$2}'

up: ## Build and start the whole stack (VictoriaMetrics, Grafana, fleet-sim, n8n, voice app)
	$(COMPOSE) up -d --build

down: ## Stop the stack (keeps volumes)
	$(COMPOSE) down

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Follow logs
	$(COMPOSE) logs -f --tail=50

chaos: ## Force a device offline: make chaos DEVICE=pi-3 [MINUTES=10]
	$(COMPOSE) exec -T fleet-sim python -m fleet_sim.chaos offline $(DEVICE) --minutes $(MINUTES)

recover: ## Bring a device back: make recover DEVICE=pi-3 (or DEVICE=all)
	$(COMPOSE) exec -T fleet-sim python -m fleet_sim.chaos recover $(DEVICE)

freeze: ## Stop random flapping / breach bursts (deterministic fleet)
	$(COMPOSE) exec -T fleet-sim python -m fleet_sim.chaos random off

unfreeze: ## Resume random flapping
	$(COMPOSE) exec -T fleet-sim python -m fleet_sim.chaos random on

breaches: ## Inject SLA breaches: make breaches N=3
	$(COMPOSE) exec -T fleet-sim python -m fleet_sim.chaos breaches $(or $(N),3)

dashboard: ## Regenerate the Grafana dashboard JSON
	python3 scripts/gen_dashboard.py

test: ## Unit tests (fake metrics server, mocked LLM; no Docker, no audio models)
	$(PY) -m pytest -q tests -m "not live and not models"

test-live: ## Tests against the live Docker stack (starts VictoriaMetrics + fleet-sim)
	$(PY) -m pytest -q tests -m live

eval: ## Voice eval (30 questions + 5 noisy) -> evals/results + RESULTS table
	$(PY) -m evals.run_eval
	$(PY) -m evals.report

eval-audio: ## (Re)generate the synthetic question audio
	$(PY) -m evals.make_audio

examples: ## Scripted end-to-end run over recorded audio -> examples/
	$(PY) -m scripts.run_examples
