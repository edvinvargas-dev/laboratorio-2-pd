# Evidencia: MLflow

Exportado 2026-11-15 20:58 desde `http://localhost:5050`.

## Model Registry: `novamercado-pronostico`

Alias: `anterior` → versión 4, `vigente` → versión 5

| Versión | Alias | Creada | Datos hasta | Promovido | Motivo |
|---|---|---|---|---|---|
| 1 |  | 2026-11-14 23:22:14 | 2026-02-28 | true | No hay modelo vigente; el candidato supera al baseline (88 133 vs 132 480) |
| 2 |  | 2026-11-14 23:23:49 | 2026-03-07 | true | Costo en validación 20 949 vs 20 565 del vigente (+1.9%, 7 días); se adopta el modelo con datos más recientes |
| 3 |  | 2026-11-14 23:25:23 | 2026-03-14 | true | Costo en validación 19 446 vs 20 149 del vigente (-3.5%, 7 días); se adopta el modelo con datos más recientes |
| 4 | anterior | 2026-11-14 23:28:00 | 2026-03-21 | true | Costo en validación 34 103 vs 33 844 del vigente (+0.8%, 7 días); se adopta el modelo con datos más recientes |
| 5 | vigente | 2026-11-15 20:48:33 | 2026-03-28 | true | Costo en validación 31 370 vs 33 111 del vigente (-5.3%, 7 días); se adopta el modelo con datos más recientes |

## Experimento `novamercado-pronostico`: runs

| Run | Inicio | Origen | Datos hasta | Costo prueba | Costo baseline | Costo vigente | MAE | WAPE | Filas | Promovido |
|---|---|---|---|---|---|---|---|---|---|---|
| `72fe255a` | 2026-11-14 23:22:12 | arranque | 2026-02-28 | 88,133 | 132,480 | — | 37.3 | 0.175 | 82932 | true |
| `10f5f573` | 2026-11-14 23:23:46 | airflow | 2026-03-07 | 20,949 | 25,385 | 20,565 | 36.8 | 0.168 | 83688 | true |
| `61c57d18` | 2026-11-14 23:25:21 | airflow | 2026-03-14 | 19,446 | 26,619 | 20,149 | 36.1 | 0.167 | 84456 | true |
| `5b5e9a72` | 2026-11-14 23:27:58 | airflow | 2026-03-21 | 34,103 | 45,399 | 33,844 | 57.9 | 0.220 | 85296 | true |
| `fc029bdf` | 2026-11-15 20:48:28 | airflow | 2026-03-28 | 31,370 | 37,581 | 33,111 | 54.5 | 0.215 | 86136 | true |

## Linaje del último run

- run `fc029bdf79224e4f888e57a257403736` · artefactos: `mlflow-artifacts:/1/fc029bdf79224e4f888e57a257403736/artifacts`
- parámetros: `tipo=lgbm`, `datos_hasta=2026-03-28`, `inicio_calibracion=2026-02-22`, `inicio_prueba=2026-03-22`, `n_filas=86136`, `n_iter=1426`, `dias_prueba=7`
- etiquetas: `version_vigente_previa=4`, `origen=airflow`, `airflow_run_id=rt_2dbde7b144ef44f28c03c45b25cedce4`, `promovido=true`, `motivo=Costo en validación 31 370 vs 33 111 del vigente (-5.3%, 7 días); se adopta el modelo con datos más recientes`
- entradas registradas: ventas_entrenamiento
- artefactos: `modelo/` (pyfunc + pronosticador.pkl), `factores_cantidad_sugerida.json`, `datos_entrenamiento.json`, `importancia_features.json`
