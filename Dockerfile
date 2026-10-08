FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce
ENV PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 make \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY src ./src
COPY tests ./tests
COPY Makefile ./
RUN pip install --no-cache-dir --no-deps . && python -m pytest -q
CMD ["python", "-m", "ice_network.cli", "run", "--output", "/app/artifacts"]
