FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/gen
COPY pyproject.toml ./
COPY zavozik_ml ./zavozik_ml
RUN pip install --no-cache-dir .
COPY gen ./gen
RUN useradd --system --uid 10001 ml
USER ml
EXPOSE 50051
CMD ["python", "-m", "zavozik_ml.serving.server"]
