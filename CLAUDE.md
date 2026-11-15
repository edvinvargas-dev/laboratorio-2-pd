# CLAUDE.md — Contexto para el agente de programación

## Proyecto
Laboratorio 2 de Product Development: servicio de pronóstico diario de ventas por
tienda y familia de producto para NovaMercado (10 tiendas, 12 familias).
Stack: FastAPI + PostgreSQL + MLflow + Apache Airflow, todo con `docker compose up`.

## Estructura
- `api/` — servicio FastAPI (puerto 8000). Endpoints delgados; la limpieza vive en `api/app/limpieza/`.
- `ml/` — features, baseline, modelo ML, métrica de costo, criterio de promoción.
- `airflow/dags/` — DAG de reentrenamiento.
- `db/` — esquema SQL de la base de datos propia del producto.
- `data/` — archivos del GES (NO se versiona).
- `notebooks/` — exploración de datos.
- `evidencia/` — capturas y respuestas de ejemplo para la entrega.

## Reglas que no se negocian (del enunciado)
- El contrato del Anexo se cumple exactamente: no omitir ni renombrar campos.
- Nunca usar el reloj del sistema para validar fechas: las fechas son simuladas.
- Al predecir una fecha solo se usan observaciones de días anteriores.
- `cantidad_sugerida` entero ≥ 0; `version_modelo` es texto.
- Observaciones idempotentes: reenvío idéntico → `registros_guardados = 0`.
- Imágenes Docker con versión fija; nada de datos ni credenciales en imágenes o repo.
- El servicio de MLflow en compose se llama `mlflow`.
- Pruebas con pytest que no dependan de MLflow en ejecución.

## Datos
- Histórico: 2024-03-01 a 2026-02-28. Tienda 10 abrió 2025-03-15.
- Costo = c_faltante·max(real−sug,0) + c_sobrante·max(sug−real,0), por familia (`costos.csv`).
- `feriados.csv`: `ambito` = `nacional` o nombre de ciudad (coincide con `tiendas.ciudad`).

## Idioma
Código, comentarios y documentación en español.
