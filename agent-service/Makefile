# agent-service — OneNeo Bank concierge API. Two interchangeable backends, two venvs:
#   * transformers (model in-process, one proc) -> .venv       + requirements.txt      (INSTALL.md)
#   * vLLM (separate model server + gateway)     -> .venv-vllm  + requirements-vllm.txt (INSTALL-VLLM.md)
# Both expose the SAME /v1/* API on API_PORT (default :8000) — run only ONE of them there.
#
# Quick start:
#   transformers:  make install       && make serve-api
#   vLLM        :  make install-vllm   && make serve-vllm       # terminal 1 (model, :8001)
#                                         make serve-vllm-api    # terminal 2 (gateway, :8000)

VENV      := .venv
VENV_VLLM := .venv-vllm
# Override if your python3.12 lacks venv/ensurepip, e.g.:
#   make install PYTHON=~/.pyenv/versions/3.12.10/bin/python
PYTHON    ?= python3.12
PY        := $(VENV)/bin/python
PY_VLLM   := $(VENV_VLLM)/bin/python
PIP       := $(VENV)/bin/pip
PIP_VLLM  := $(VENV_VLLM)/bin/pip

.PHONY: help install install-vllm serve-api serve-vllm serve-vllm-api clean

help:
	@echo "Transformers backend (model in-process, one process):"
	@echo "  make install         create .venv + install requirements.txt (torch separately: INSTALL.md)"
	@echo "  make serve-api       run the agent API (agent.api) on API_PORT, default :8000"
	@echo ""
	@echo "vLLM backend (separate model server + gateway, two processes):"
	@echo "  make install-vllm    create .venv-vllm + install requirements-vllm.txt"
	@echo "  make serve-vllm      run the vLLM model server (run_vllm_server.sh) on :8001   [terminal 1]"
	@echo "  make serve-vllm-api  run the vLLM gateway (agent.api_vllm) on API_PORT :8000   [terminal 2]"
	@echo ""
	@echo "  make clean           remove __pycache__"

# --- transformers backend -----------------------------------------------------
$(VENV):
	$(PYTHON) -m venv $(VENV)

install: $(VENV)
	$(PIP) install -U pip
	@$(PY) -c "import torch" 2>/dev/null || { \
	  echo "ERROR: install the CUDA-matched torch wheel FIRST (see INSTALL.md step 3), e.g.:"; \
	  echo "  $(PIP) install torch torchvision"; exit 1; }
	$(PIP) install -r requirements.txt

serve-api:
	$(PY) -m agent.api

# --- vLLM backend -------------------------------------------------------------
$(VENV_VLLM):
	$(PYTHON) -m venv $(VENV_VLLM)

install-vllm: $(VENV_VLLM)
	$(PIP_VLLM) install -U pip
	$(PIP_VLLM) install -r requirements-vllm.txt

serve-vllm:
	./run_vllm_server.sh

serve-vllm-api:
	$(PY_VLLM) -m agent.api_vllm

clean:
	rm -rf agent/__pycache__
