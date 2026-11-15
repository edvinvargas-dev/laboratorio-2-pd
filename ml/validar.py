"""Primera tarea del DAG: verificar que los insumos del reentrenamiento estén disponibles.

Falla rápido y con un mensaje claro si falta la base de datos, MLflow o los datos.
Uso:  python -m ml.validar
"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path


def main() -> None:
    errores = []
    data = Path(os.getenv("DATA_DIR", "data"))
    for archivo in ["historico_ventas.csv", "tiendas.csv", "familias.csv", "feriados.csv", "costos.csv"]:
        if not (data / archivo).exists():
            errores.append(f"falta {data / archivo}")

    uri = os.getenv("MLFLOW_TRACKING_URI", "")
    try:
        urllib.request.urlopen(f"{uri.rstrip('/')}/health", timeout=10)
    except Exception as e:
        errores.append(f"MLflow no disponible en {uri}: {e}")

    url = os.getenv("DATABASE_URL")
    if url:
        try:
            import psycopg

            with psycopg.connect(url, connect_timeout=10) as c:
                n, obs = c.execute(
                    "SELECT count(*), count(*) FILTER (WHERE origen = 'observacion') FROM ventas_conocidas"
                ).fetchone()
            print(f"ventas conocidas: {n} (observaciones de la operación: {obs})")
            if n == 0:
                errores.append("la base no tiene ventas: falta cargar el histórico")
        except Exception as e:
            errores.append(f"base de datos no disponible: {e}")

    if errores:
        print("Insumos no disponibles:\n  - " + "\n  - ".join(errores), file=sys.stderr)
        sys.exit(1)
    print("insumos OK")


if __name__ == "__main__":
    main()
