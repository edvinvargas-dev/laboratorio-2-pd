# CLAUDE.md — Contexto para el agente de programación

## Proyecto
Laboratorio 2 de Product Development: servicio de pronóstico diario de ventas por
tienda y familia de producto para NovaMercado (10 tiendas, 12 familias).
Stack: FastAPI + PostgreSQL + MLflow + Apache Airflow, todo con `docker compose up`.
Decisiones y su justificación: `DECISIONES.md`. Instrucciones de uso: `README.md`.

## Estructura
- `api/app/main.py` — endpoints delgados; leen JSON crudo y delegan.
- `api/app/limpieza/` — defensa del contrato (Python puro): `texto.py`, `valores.py`,
  `campos.py`, `solicitudes.py` (políticas reparar / advertir / rechazar).
- `api/app/servicios/` — `prediccion.py`; repositorio (`repositorio.py` en memoria,
  `repositorio_pg.py` PostgreSQL); modelo (`modelo.py`, `modelo_mlflow.py` sigue el alias);
  orquestador (`orquestador.py` falso, `orquestador_airflow.py` API REST v2).
- `api/app/dependencias.py` — configuración por entorno (`Config.desde_entorno`) y armado.
- `api/app/arranque.py` — servicio de arranque: esquema + histórico + primer modelo.
- `ml/` — `features.py` (misma función en entrenamiento y servicio), `modelos.py`,
  `costos.py`, `entrenar.py`, `criterio.py`, `registro.py` (MLflow), `pipeline.py`
  (ciclo completo), `datos.py`, `validar.py`.
- `airflow/` — Dockerfile (venv aislado para `ml/`) y `dags/reentrenamiento.py`.
- `db/esquema.sql` — esquema idempotente; vistas `ventas_conocidas` y `ventas_entrenamiento`.
- `scripts/` — evaluador, simulador, ejemplos, reentrenar, exportar evidencia.
- `data/` — archivos del GES (NO se versiona). `evidencia/` — entregables de evidencia.

## Comandos
- Pruebas: `.venv/Scripts/python -m pytest` (sin servicios externos; las de PostgreSQL
  corren solo con `TEST_DATABASE_URL`).
- Producto: `docker compose up -d --build`; salud: `curl localhost:8000/health`.
- Evaluación completa: `python scripts/evaluador.py --proyecto novamercado`.

## Reglas que no se negocian (del enunciado)
- El contrato del Anexo se cumple exactamente: no omitir ni renombrar campos.
- Nunca usar el reloj del sistema para validar fechas: las fechas son simuladas.
- Al predecir una fecha solo se usan observaciones de días anteriores.
- `cantidad_sugerida` entero ≥ 0; `version_modelo` es texto.
- Observaciones idempotentes: reenvío idéntico → `registros_guardados = 0`.
- Imágenes Docker con versión fija; nada de datos ni credenciales en imágenes o repo.
- El servicio de MLflow en compose se llama `mlflow`.
- Pruebas con pytest que no dependan de MLflow en ejecución.
- El alias `vigente` se mueve solo en el último paso del pipeline.

## Datos
- Histórico: 2024-03-01 a 2026-02-28. Tienda 10 abrió 2025-03-15.
- Costo = c_faltante·max(real−sug,0) + c_sobrante·max(sug−real,0), por familia (`costos.csv`).
- `feriados.csv`: `ambito` = `nacional` o nombre de ciudad (coincide con `tiendas.ciudad`).

## Idioma
Código, comentarios y documentación en español.
