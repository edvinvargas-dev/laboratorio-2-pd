# Imagen de la API (y del servicio de arranque, que usa el mismo código).
FROM python:3.12.14-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY ml/requirements.txt ml/requirements.txt
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY ml ml
COPY api/app api/app
COPY db db

ENV PYTHONPATH=/srv:/srv/api \
    PYTHONUNBUFFERED=1 \
    MLFLOW_DISABLE_AGENT_HINT=1 \
    GIT_PYTHON_REFRESH=quiet \
    DATA_DIR=/srv/data \
    CACHE_MODELO=/srv/cache_modelo

RUN useradd --uid 1000 --create-home app && mkdir -p /srv/cache_modelo && chown app /srv/cache_modelo
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
