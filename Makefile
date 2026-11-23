# fleet-voice-agent. Run `make help` for targets.
SHELL := /bin/bash
PY ?= .venv/bin/python
DEVICE ?= pi-3
MINUTES ?= 10
COMPOSE ?= docker compose

.PHONY: help up down ps logs chaos recover freeze unfreeze breaches test test-live eval eval-noise eval-stt eval-langid eval-audio examples examples-webrtc alert-timeline models dashboard

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

eval-noise: ## Round 2: noise sweep (white + babble/fan at 20/10/5 dB): WER + tool choice (rules; Claude on 10 dB)
	$(PY) -m evals.noise_sweep --claude

eval-stt: ## Round 2: Whisper small vs medium vs large-v3-turbo on Marathi (needs `make models-extra`)
	$(PY) -m evals.compare_stt --model whisper-small whisper-medium whisper-large-v3-turbo --langs mr

eval-langid: ## Round 2: en/hi/mr language-ID confusion matrices from logged runs
	$(PY) -m evals.lang_confusion

eval-audio: ## (Re)generate the synthetic question audio
	$(PY) -m evals.make_audio

examples: ## Scripted end-to-end run over recorded audio -> examples/offline/
	$(PY) -m scripts.run_examples

examples-webrtc: ## Same over a real WebRTC session (app must be running on 17860)
	$(PY) -m scripts.webrtc_client --out examples/webrtc evals/audio/en01.wav evals/audio/hi01.wav evals/audio/mr01.wav

alert-timeline: ## make chaos -> Grafana -> n8n -> voice note, with timings
	$(PY) -m scripts.alert_timeline --device $(DEVICE)

models: ## Download Whisper small + Piper voices into ./models (~780 MB)
	$(PY) scripts/download_models.py

models-extra: ## Round 2 only: Whisper medium + large-v3-turbo (CTranslate2) for `make eval-stt` (~3.1 GB)
	$(PY) scripts/download_models.py --extra
