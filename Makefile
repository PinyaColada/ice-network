PYTHON ?= .venv/bin/python

.PHONY: simulate test lint run
simulate:
	$(PYTHON) -m ice_network.cli simulate
test:
	$(PYTHON) -m pytest -q
lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
run: simulate
