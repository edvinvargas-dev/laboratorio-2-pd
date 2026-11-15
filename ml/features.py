"""Construcción de features. Una sola función para entrenamiento y predicción.

Regla central: la feature de una fila (tienda, familia, fecha d) solo usa ventas de
fechas < d. Así el modelo entrena con la misma información que tendrá el servicio,
donde la observación de d−1 llega antes de la solicitud de d.

Entradas:
  historia  : fecha, tienda_id, familia_id, ventas            (ventas pasadas conocidas)
  objetivos : fecha, tienda_id, familia_id, en_promocion      (filas a predecir)

En entrenamiento `objetivos` son las propias filas del histórico; en la API son las
familias de la solicitud y `historia` sale de la base de datos.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from ml.catalogos import TIPOS_TIENDA, Catalogos

LAGS = [1, 2, 3, 4, 5, 6, 7, 14, 21, 28]
VENTANA_MAX = 28  # días de historia que necesita una predicción

FEATURES = (
    ["tienda_id", "familia_cod", "tipo_tienda", "dias_desde_apertura", "en_promocion"]
    + ["dia_semana", "dia_mes", "mes", "dia_anio", "es_fin_mes", "dias_a_fin_mes"]
    + ["tipo_fecha", "tipo_fecha_ayer", "tipo_fecha_manana"]
    + [f"lag_{k}" for k in LAGS]
    + ["media_7", "media_28", "std_28", "mismo_dia_mediana", "mismo_dia_media"]
)
CATEGORICAS = ["tienda_id", "familia_cod", "tipo_tienda", "tipo_fecha", "tipo_fecha_ayer", "tipo_fecha_manana"]


def _matriz_ventas(historia: pd.DataFrame, fechas: pd.DatetimeIndex, series: pd.MultiIndex) -> pd.DataFrame:
    """Matriz fecha × (tienda, familia). Los días sin dato quedan como NaN."""
    if historia.empty:
        return pd.DataFrame(np.nan, index=fechas, columns=series)
    w = historia.pivot_table(index="fecha", columns=["tienda_id", "familia_id"], values="ventas", aggfunc="last")
    return w.reindex(index=fechas, columns=series)


def construir_features(historia: pd.DataFrame, objetivos: pd.DataFrame, cat: Catalogos) -> pd.DataFrame:
    obj = objetivos.copy()
    obj["fecha"] = pd.to_datetime(obj["fecha"])
    obj["tienda_id"] = obj["tienda_id"].astype(int)
    hist = historia[["fecha", "tienda_id", "familia_id", "ventas"]].copy()
    hist["fecha"] = pd.to_datetime(hist["fecha"])
    hist["tienda_id"] = hist["tienda_id"].astype(int)
    # Nunca usar ventas del mismo día o posteriores al objetivo más tardío
    hist = hist[hist.fecha < obj.fecha.max()]

    inicio = min(obj.fecha.min() - pd.Timedelta(days=VENTANA_MAX), hist.fecha.min() if len(hist) else obj.fecha.min())
    fechas = pd.date_range(inicio, obj.fecha.max(), freq="D")
    series = pd.MultiIndex.from_frame(obj[["tienda_id", "familia_id"]].drop_duplicates())
    w = _matriz_ventas(hist, fechas, series)

    # Índices para leer cada objetivo de las matrices (fila = fecha, columna = serie)
    fi = fechas.get_indexer(obj.fecha)
    ci = series.get_indexer(pd.MultiIndex.from_frame(obj[["tienda_id", "familia_id"]]))

    def leer(m: pd.DataFrame) -> np.ndarray:
        return m.to_numpy()[fi, ci]

    for k in LAGS:
        obj[f"lag_{k}"] = leer(w.shift(k))
    pasado = w.shift(1)  # todo lo anterior a la fecha objetivo
    obj["media_7"] = leer(pasado.rolling(7, min_periods=1).mean())
    obj["media_28"] = leer(pasado.rolling(28, min_periods=1).mean())
    obj["std_28"] = leer(pasado.rolling(28, min_periods=2).std())
    mismo_dia = obj[["lag_7", "lag_14", "lag_21", "lag_28"]].to_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)  # filas sin ningún dato
        obj["mismo_dia_mediana"] = np.nanmedian(mismo_dia, axis=1)
        obj["mismo_dia_media"] = np.nanmean(mismo_dia, axis=1)

    # Calendario
    f = obj.fecha
    obj["dia_semana"] = f.dt.day_of_week
    obj["dia_mes"] = f.dt.day
    obj["mes"] = f.dt.month
    obj["dia_anio"] = f.dt.day_of_year
    obj["es_fin_mes"] = f.dt.is_month_end.astype(int)
    obj["dias_a_fin_mes"] = (f.dt.days_in_month - f.dt.day).astype(int)

    # Feriados y fechas especiales que aplican a la tienda (hoy, ayer, mañana)
    esp = cat.fechas_especiales()
    for col, delta in [("tipo_fecha", 0), ("tipo_fecha_ayer", -1), ("tipo_fecha_manana", 1)]:
        clave = obj[["tienda_id"]].assign(fecha=f + pd.Timedelta(days=delta))
        obj[col] = clave.merge(esp, on=["fecha", "tienda_id"], how="left").tipo_fecha.fillna(0).astype(int).to_numpy()

    # Tienda y familia
    t = cat.tiendas.set_index("tienda_id")
    obj["tipo_tienda"] = obj.tienda_id.map(t.tipo.map(TIPOS_TIENDA)).astype(int)
    apertura = obj.tienda_id.map(t.fecha_apertura)
    obj["dias_desde_apertura"] = (f - apertura).dt.days.clip(lower=0, upper=400)
    obj["familia_cod"] = obj.familia_id.map(cat.codigo_familia()).astype(int)
    obj["en_promocion"] = obj["en_promocion"].astype(float)
    return obj
