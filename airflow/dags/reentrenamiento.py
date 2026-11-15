"""DAG de reentrenamiento de NovaMercado.

Se dispara desde la API (POST /admin/reentrenar → API REST de Airflow); no tiene
calendario propio. Usa el histórico y las observaciones registradas en la base del
producto, compara contra el modelo vigente y, si el criterio lo aprueba, mueve el
alias `vigente` en MLflow. La API detecta el cambio sola en menos de 15 s.

Tareas:
  validar_insumos → reentrenar
- validar_insumos: base de datos, MLflow y archivos disponibles (falla rápido).
- reentrenar:      ml.pipeline; su última línea (JSON con estado, promovido,
                   version y motivo) queda como XCom y la API la devuelve.

Las tareas usan el entorno aislado del modelo ($ML_PYTHON), no el Python de Airflow.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

ENTORNO = {"PYTHONPATH": "/opt/proyecto", "MLFLOW_DISABLE_AGENT_HINT": "1"}

with DAG(
    dag_id="reentrenamiento",
    description="Reentrena el pronóstico de ventas y promueve el modelo si supera el criterio",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,  # dos disparos seguidos se ejecutan uno tras otro
    is_paused_upon_creation=False,
    dagrun_timeout=timedelta(minutes=10),
    default_args={"retries": 0},
    tags=["novamercado", "ml"],
) as dag:
    validar = BashOperator(
        task_id="validar_insumos",
        bash_command="cd $PROYECTO_DIR && $ML_PYTHON -m ml.validar",
        env=ENTORNO,
        append_env=True,
        execution_timeout=timedelta(minutes=1),
    )
    reentrenar = BashOperator(
        task_id="reentrenar",
        bash_command=(
            "cd $PROYECTO_DIR && $ML_PYTHON -m ml.pipeline --una-linea "
            "--etiqueta origen=airflow --etiqueta airflow_run_id={{ run_id }}"
        ),
        env=ENTORNO,
        append_env=True,
        do_xcom_push=True,  # última línea de la salida = resultado JSON
        execution_timeout=timedelta(minutes=9),
    )
    validar >> reentrenar
