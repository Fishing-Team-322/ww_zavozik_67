FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/gen
# lightgbm требует OpenMP
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY requirements.lock ./
COPY zavozik_ml ./zavozik_ml
# Структурная модель M6 (cashradar): numpy, pandas, pyyaml; LightGBM-артефакт внутри колеса
COPY vendor ./vendor
# Optional neural runtimes; the default v1/forecast image is unchanged.
ARG ML_EXTRA=""
RUN case "$ML_EXTRA" in ""|encoder|encoder-torch|discovery) ;; *) exit 1 ;; esac \
    && if [ "$ML_EXTRA" = encoder-torch ] || [ "$ML_EXTRA" = discovery ]; then \
         pip install --no-cache-dir 'torch>=2.5' --index-url https://download.pytorch.org/whl/cpu; \
       fi \
    && if [ -n "$ML_EXTRA" ]; then \
         pip install --no-cache-dir -c requirements.lock ".[${ML_EXTRA}]"; \
       else pip install --no-cache-dir -c requirements.lock .; fi
RUN pip install --no-cache-dir -c requirements.lock vendor/cashradar-*.whl
COPY gen ./gen
COPY artifacts ./artifacts
ENV ML_ARTIFACTS=/app/artifacts
RUN useradd --system --uid 10001 ml
USER ml
EXPOSE 50051
CMD ["python", "-m", "zavozik_ml.serving.server"]
