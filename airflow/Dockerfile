# Airflow con un entorno virtual aislado para el código de ml/.
# Las tareas ejecutan /home/airflow/ml-venv/bin/python, así las versiones de pandas,
# numpy, LightGBM y MLflow del modelo no chocan con las constraints de Airflow.
FROM apache/airflow:3.3.2-python3.12

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*
USER airflow

COPY --chown=airflow:root ml/requirements.txt /tmp/ml-requirements.txt
RUN python -m venv /home/airflow/ml-venv \
 && /home/airflow/ml-venv/bin/pip install --no-cache-dir -r /tmp/ml-requirements.txt

COPY --chown=airflow:root ml /opt/proyecto/ml
COPY --chown=airflow:root airflow/dags /opt/airflow/dags

ENV ML_PYTHON=/home/airflow/ml-venv/bin/python \
    PROYECTO_DIR=/opt/proyecto
