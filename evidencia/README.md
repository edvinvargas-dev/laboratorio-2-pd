# Evidencia de funcionamiento

Todo lo de esta carpeta se generó con el producto **clonado desde GitHub y levantado
desde cero** (`docker compose up`), siguiendo el README.

| Archivo | Contenido |
|---|---|
| [evaluacion.md](evaluacion.md) / `.json` | 28 días de operación simulada: 3 204 predicciones, 0 errores de contrato, costo 39% menor que el baseline, reentrenamientos, caída de MLflow, `down`/`up` y cambio de demanda |
| [mlflow.md](mlflow.md) | Versiones del modelo con alias y motivo de cada decisión; runs con métricas técnicas y de costo; linaje |
| [airflow.md](airflow.md) | Ejecuciones del DAG de reentrenamiento (exitosas y una fallida), tareas y resultado |
| [respuestas/](respuestas/) | Respuestas de la API a los ejemplos del GES (válidos y E01–E10) |
| [respuestas/otros_casos.json](respuestas/otros_casos.json) | Rechazos 422, `/modelo`, `/health` y 404 de reentrenamiento |
| [capturas/](capturas/) | MLflow (registro, runs, detalle de un run) y Airflow (ejecuciones, grafo del DAG) |

Se regenera con `scripts/evaluador.py`, `scripts/exportar_evidencia.py`,
`scripts/probar_ejemplos.py` y `scripts/otros_casos.py`.

---

## Revisión contra el enunciado

### 1. Servicio con FastAPI

| Requisito | Dónde | Evidencia |
|---|---|---|
| Contrato exacto del Anexo (puerto 8000, campos, códigos) | `api/app/main.py`, `api/app/schemas.py` | `api/tests/test_contrato.py`; 0 errores en `evaluacion.md` |
| Validación con Pydantic; limpieza en módulos con pruebas, fuera de los endpoints | `api/app/limpieza/` | `api/tests/test_limpieza.py` (E01–E10 y casos fuera del catálogo) |
| Política explícita reparar / advertir / rechazar, con reglas generales | `api/app/limpieza/solicitudes.py`; DECISIONES §1 | 171 solicitudes con defectos nuevos en `evaluacion.md`, ninguna rompió el contrato |
| Versión del modelo en cada respuesta | `version_modelo` | `respuestas/*.json` |
| Pruebas pytest sin MLflow en ejecución | `api/tests`, `ml/tests` | 135 pruebas; MLflow y Airflow simulados |

### 2. Persistencia

| Requisito | Dónde | Evidencia |
|---|---|---|
| PostgreSQL propia, en Docker, separada de la de Airflow | servicios `db` y `airflow-db` | `docker-compose.yml` |
| Se registran solicitudes, predicciones, correcciones y observaciones | `db/esquema.sql` | `api/tests/test_postgres.py` |
| Observaciones idempotentes | *upsert* en `repositorio_pg.py` | reenvíos con `registros_guardados = 0` en `evaluacion.md` |
| Se conserva al detener y levantar | volúmenes nombrados | evento `down_up` en `evaluacion.md` |

### 3. Modelado y MLflow

| Requisito | Dónde | Evidencia |
|---|---|---|
| Baseline simple y modelo de ML que lo mejora | `ml/modelos.py` | DECISIONES §4; costo 33.5% menor en la prueba |
| Métrica de negocio con `costos.csv`; cantidad sugerida coherente con los costos | `ml/costos.py` | DECISIONES §3; métricas `costo*` en `mlflow.md` |
| Experimentos, modelos y linaje en MLflow; vigente identificado con un alias | `ml/registro.py` | `mlflow.md`; `capturas/mlflow_*.jpg` |
| Criterio explícito y automatizado de reemplazo | `ml/criterio.py` | DECISIONES §8; motivo en cada versión |

### 4. Reentrenamiento con Airflow

| Requisito | Dónde | Evidencia |
|---|---|---|
| DAG con histórico y observaciones de la base | `airflow/dags/reentrenamiento.py`, vista `ventas_entrenamiento` | `airflow.md`; filas por origen en el linaje |
| Se dispara por el endpoint; el estado se puede consultar | `orquestador_airflow.py` | `evaluacion.md`, `airflow.md` |
| El modelo promovido se usa sin reinicio en ≤ 2 min | `modelo_mlflow.py` (revisa el alias cada 15 s) | adopción en 0–6 s en `evaluacion.md` |
| Un reentrenamiento fallido o no aprobado no afecta al vigente | el alias se mueve al final | ejecución fallida en `airflow.md`; el vigente no cambió |

### 5. Contenedores y operación

| Requisito | Dónde | Evidencia |
|---|---|---|
| Todo con `docker compose up`; servicio `mlflow` con ese nombre | `docker-compose.yml`, README | clon desde cero: `ok` en 128 s |
| Desde cero entrena y registra el primer modelo; al volver no repite | `api/app/arranque.py` | versión 1 con origen `arranque` en `mlflow.md` |
| Imágenes con versiones fijas; sin datos ni credenciales en imágenes o repo; `.env.example` | Dockerfiles, `.dockerignore`, `.gitignore` | — |
| Responde sin MLflow; `/health` degradado en < 1 min y `ok` en < 2 min al volver | caché local del modelo | 14 s y 12 s en `evaluacion.md` |
| Listo en ≤ 10 min; cada reentrenamiento ≤ 10 min | — | 128 s; reentrenamientos de 51–115 s |

### 6. Documentación

| Requisito | Dónde |
|---|---|
| Repositorio con estructura clara y archivo de contexto para el agente | `CLAUDE.md` |
| README con instrucciones desde cero y la carpeta de los datos | `README.md` (paso 2: `data/`) |
| DECISIONES con política de datos, información del modelo, cantidad sugerida y criterio de reemplazo | `DECISIONES.md` §1, §2, §3 y §8 |
