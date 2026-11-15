# NovaMercado — Servicio de pronóstico diario de ventas

Laboratorio 2 de Product Development. Este servicio pronostica las ventas diarias por
tienda y familia de producto y sugiere cuánto tener disponible según el costo de faltar
o sobrar. También:

- defiende el contrato ante datos defectuosos: repara, advierte o rechaza, e informa qué
  hizo;
- registra cada predicción y cada venta real;
- se reentrena con esa información y adopta el modelo nuevo sin reinicio manual.

```
                     ┌──────────────────────┐
  tiendas ──HTTP──▶  │ api  (FastAPI :8000) │──── lee/escribe ───▶ db (PostgreSQL del producto)
                     └──────────┬───────────┘
              sigue el alias    │      POST /admin/reentrenar
              "vigente" (15 s)  │                 │
                     ┌──────────▼──────┐   ┌──────▼──────────────────┐
                     │ mlflow (:5000)  │◀──│ airflow (:8080)          │──▶ airflow-db
                     │ runs + registry │   │ DAG reentrenamiento      │
                     └─────────────────┘   └──────────────────────────┘
  arranque: al levantar, carga el histórico y entrena el primer modelo si no existe.
```

Las decisiones técnicas y de producto, con sus alternativas, están en
[DECISIONES.md](DECISIONES.md).

---

## Levantar el producto desde cero

**Requisitos:** Docker con Docker Compose v2, al menos **6 GB de RAM** asignados a Docker
y los puertos 8000, 5000, 8080 y 5433 libres.

1. **Clonar el repositorio en el tag de entrega**

   ```bash
   git clone https://github.com/edvinvargas-dev/laboratorio-2-pd.git
   cd laboratorio-2-pd
   git checkout entrega-lab2
   ```

2. **Colocar los archivos publicados en el GES en la carpeta `data/`** (en la raíz del
   repositorio). La carpeta no se versiona. Debe quedar así:

   ```
   data/
   ├── tiendas.csv
   ├── familias.csv
   ├── historico_ventas.csv
   ├── feriados.csv
   ├── costos.csv
   ├── catalogo_errores.md
   └── ejemplos/            (opcional: solo lo usan los scripts de prueba)
   ```

3. **Crear el archivo de configuración.** Se pueden cambiar las claves; los valores de
   ejemplo funcionan.

   ```bash
   cp .env.example .env          # en Windows (cmd): copy .env.example .env
   ```

4. **Levantar todo**

   ```bash
   docker compose up -d --build
   ```

5. **Esperar a que `/health` responda `ok`.** Tarda unos 3 minutos sin contar la
   construcción de las imágenes:

   ```bash
   curl http://localhost:8000/health
   ```

   Mientras no haya modelo, responde 503. El servicio `arranque` carga el histórico en la
   base, entrena el primer modelo y lo registra en MLflow con el alias `vigente`. La API
   lo carga sola.

### Detener y volver a levantar

```bash
docker compose down        # conserva los datos (volúmenes)
docker compose up -d       # retoma lo que había: no recarga datos ni reentrena
```

Para empezar realmente de cero (borra base, modelos y registros):
`docker compose down -v`.

---

## Uso

El contrato completo está en el Anexo del enunciado. La documentación interactiva está en
http://localhost:8000/docs.

```bash
# Pronóstico de un día
curl -X POST http://localhost:8000/v1/prediccion -H "Content-Type: application/json" \
  -d '{"tienda_id": 5, "fecha": "2026-03-01", "familias": [{"familia_id": "abarrotes", "en_promocion": 0}]}'

# Ventas reales del día (idempotente: reenviar lo mismo guarda 0 registros)
curl -X POST http://localhost:8000/v1/observaciones -H "Content-Type: application/json" \
  -d '{"tienda_id": 5, "fecha": "2026-03-01", "ventas": [{"familia_id": "abarrotes", "ventas": 994}]}'

# Reentrenar y consultar el estado
curl -X POST http://localhost:8000/admin/reentrenar
curl http://localhost:8000/admin/reentrenar/<id>

# Modelo vigente y estado del servicio
curl http://localhost:8000/modelo
curl http://localhost:8000/health
```

| Interfaz | URL | Acceso |
|---|---|---|
| API (Swagger) | http://localhost:8000/docs | — |
| MLflow | http://localhost:5000 | — |
| Airflow | http://localhost:8080 | usuario `AIRFLOW_USUARIO` y clave `AIRFLOW_CLAVE` de `.env` |

### Scripts de prueba (requieren Python con pandas)

```bash
python scripts/probar_ejemplos.py       # envía data/ejemplos y guarda las respuestas en evidencia/
python scripts/simular_operacion.py --desde 2026-03-01 --dias 7 --factor 1.2   # días simulados
python scripts/reentrenar.py            # dispara un reentrenamiento y espera el resultado
python scripts/evaluador.py --proyecto novamercado   # 28 días como el evaluador: defectos, reentrenos,
                                                     # caída de MLflow, down/up y cambio de demanda
```

El último resultado del evaluador (producto clonado desde GitHub y levantado desde cero) está
en [evidencia/evaluacion.md](evidencia/evaluacion.md): **0 errores de contrato** en 3 204
predicciones y un costo **39% menor** que el baseline.

---

## Estructura del repositorio

```
api/            Servicio FastAPI
  app/main.py         endpoints (delgados)
  app/schemas.py      modelos Pydantic del contrato
  app/limpieza/       políticas reparar / advertir / rechazar (Python puro, con pruebas)
  app/servicios/      predicción, repositorio (memoria / PostgreSQL), modelo (MLflow), Airflow
  app/arranque.py     servicio de arranque (datos + primer modelo)
  tests/              pytest: contrato, limpieza, MLflow y Airflow simulados, PostgreSQL
  Dockerfile
ml/             Modelo: features, baseline, LightGBM, costo, criterio, registro, pipeline
airflow/        Dockerfile y dags/reentrenamiento.py
db/esquema.sql  Esquema de la base del producto
scripts/        Pruebas de punta a punta contra la API
notebooks/      Exploración de datos
evidencia/      Respuestas de ejemplo, capturas de MLflow y Airflow
docker-compose.yml  .env.example  DECISIONES.md  CLAUDE.md
```

---

## Desarrollo y pruebas

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt    # Linux/Mac: .venv/bin/python
.venv/Scripts/python -m pytest
```

Las pruebas **no** necesitan MLflow, Airflow ni los archivos del GES: usan datos
sintéticos y dobles de prueba. Las pruebas contra PostgreSQL real se ejecutan solo si
existe `TEST_DATABASE_URL`, que debe apuntar a una base desechable porque se borra su
esquema.

Entrenar y comparar modelos fuera de Docker: `python -m ml.entrenar --data data`.

---

## Tiempos medidos (Docker Desktop, 4 CPU, 6 GB)

| Operación | Tiempo |
|---|---|
| `up` desde cero hasta `/health` = `ok` (sin construir imágenes) | 157 s |
| `down` + `up` conservando volúmenes | 68 s (la API sirve desde su caché a los 27 s) |
| Reentrenamiento completo por Airflow | 30–90 s |
| La API adopta un modelo promovido | ≤ 15 s |
| `/health` detecta MLflow caído / recuperado | 8 s / 29 s |
