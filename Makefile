PYTHON ?= .venv/bin/python
export OMP_NUM_THREADS = 1
export OPENBLAS_NUM_THREADS = 1
export MKL_NUM_THREADS = 1

.PHONY: setup simulate test lint run visualize demo
setup:
	python3.11 -m venv .venv
	$(PYTHON) -m pip install --require-hashes -r requirements.lock
	$(PYTHON) -m pip install --no-deps -e .
simulate:
	$(PYTHON) -m ice_network.cli simulate
test:
	$(PYTHON) -m pytest -q
lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
run:
	$(PYTHON) -m ice_network.cli run
visualize:
	$(PYTHON) -m ice_network.cli visualize
demo: visualize
	cp artifacts/replay.html docs/index.html
