# OneNeo Bank concierge demo — data production pipeline.
#
# The authored source of truth is the Markdown under docs/profiles/ (the ```yaml
# facts``` blocks and the dimension taxonomy). These targets compile that source
# into reproducible artifacts under DATA/ (git-ignored).

PY := .venv/bin/python

.PHONY: help facts persona check all clean

help:
	@echo "Targets:"
	@echo "  make facts    - compile docs/profiles ```facts``` blocks -> DATA/products.yaml, DATA/campaigns.yaml"
	@echo "  make persona  - generate the synthetic persona population (pipeline/generate_personas.py)"
	@echo "  make check    - validate the facts blocks (drift check) without writing"
	@echo "  make all      - facts + persona"
	@echo "  make clean    - remove generated DATA/ artifacts"

facts:
	$(PY) pipeline/build_facts.py

persona:
	$(PY) pipeline/generate_personas.py

check:
	$(PY) pipeline/build_facts.py --check

all: facts persona

clean:
	rm -rf DATA
