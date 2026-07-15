# OneNeo Bank concierge demo — data production pipeline.
#
# The authored source of truth is the Markdown under docs/profiles/ (the ```yaml
# facts``` blocks and the dimension taxonomy). These targets compile that source
# into reproducible artifacts under DATA/ (git-ignored).

PY := .venv/bin/python

.PHONY: help facts persona transactions kb check all clean

help:
	@echo "Targets:"
	@echo "  make facts        - compile docs/profiles ```facts``` blocks -> DATA/products.yaml, DATA/campaigns.yaml"
	@echo "  make persona      - generate the synthetic persona population (pipeline/generate_personas.py)"
	@echo "  make transactions - generate recent historical transactions per persona -> DATA/transactions.yaml"
	@echo "  make kb           - compile docs/Q&A/CMP-*_QA_examples.md -> DATA/kb-cmp-*.yaml"
	@echo "  make check        - validate the facts + Q&A knowledge base without writing"
	@echo "  make all          - facts + persona + transactions + kb"
	@echo "  make clean        - remove generated DATA/ artifacts"

facts:
	$(PY) pipeline/build_facts.py

persona:
	$(PY) pipeline/generate_personas.py

transactions:
	$(PY) pipeline/generate_historical_transactions.py

kb:
	$(PY) pipeline/build_kb.py

check:
	$(PY) pipeline/build_facts.py --check
	$(PY) pipeline/build_kb.py --check

all: facts persona transactions kb

clean:
	rm -rf DATA
