# web-app — OneNeo Bank concierge mobile-style demo. CPU-only; no model.
# First:  make install

VENV := .venv
# Override if your `python3.12` lacks venv/ensurepip, e.g.:
#   make install PYTHON=~/.pyenv/versions/3.12.10/bin/python
PYTHON ?= python3.12
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help venv install serve dev test clean

help:
	@echo "make install  - create .venv and install requirements"
	@echo "make serve     - run the app (host/port from .env, default 0.0.0.0:8090)"
	@echo "make dev       - run with autoreload"
	@echo "make test      - data-layer + endpoint smoke tests"
	@echo "make clean     - remove caches"

$(VENV):
	$(PYTHON) -m venv $(VENV)

install: $(VENV)
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt

serve:
	$(PY) -m app.main

dev:
	$(VENV)/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8090

test:
	$(PY) -m pytest -q

clean:
	rm -rf app/__pycache__ app/**/__pycache__ .pytest_cache tests/__pycache__
