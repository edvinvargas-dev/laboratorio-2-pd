"""Datos de entrenamiento: desde la base del producto (histórico + observaciones) o desde el CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.catalogos import cargar_historico

COLUMNAS = ["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"]


def cargar_datos_entrenamiento(database_url: str | None, data_dir: str | Path) -> pd.DataFrame:
    """Con base de datos usa la vista `ventas_entrenamiento`; sin ella, el histórico publicado.

    La promoción de una observación puede ser desconocida (NULL) si nunca se pidió el
    pronóstico de ese día; queda como NaN y LightGBM la trata como faltante.
    """
    if not database_url:
        return cargar_historico(data_dir)[COLUMNAS]
    import psycopg

    with psycopg.connect(database_url, connect_timeout=10) as c:
        filas = c.execute(
            "SELECT fecha, tienda_id, familia_id, ventas, en_promocion, origen FROM ventas_entrenamiento "
            "ORDER BY fecha, tienda_id, familia_id"
        ).fetchall()
    df = pd.DataFrame(filas, columns=[*COLUMNAS, "origen"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["en_promocion"] = pd.to_numeric(df["en_promocion"], errors="coerce")
    return df
