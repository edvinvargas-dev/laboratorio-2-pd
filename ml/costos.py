"""Métrica de negocio y cantidad sugerida.

costo = c_faltante · max(real − sugerido, 0) + c_sobrante · max(sugerido − real, 0)

Si la demanda fuera conocida en distribución, la cantidad que minimiza el costo esperado
es el cuantil  q* = c_faltante / (c_faltante + c_sobrante)  de esa distribución
(problema del vendedor de periódicos). En lugar de suponer una distribución, aquí
elegimos por familia el factor multiplicativo sobre el pronóstico que minimiza el costo
real en un periodo de calibración que el modelo no vio. Es la versión empírica de q*.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GRILLA_FACTORES = np.round(np.arange(0.50, 3.001, 0.01), 2)


def costo(real, sugerido, c_faltante, c_sobrante):
    real, sugerido = np.asarray(real, float), np.asarray(sugerido, float)
    return np.asarray(c_faltante) * np.maximum(real - sugerido, 0) + np.asarray(c_sobrante) * np.maximum(
        sugerido - real, 0
    )


def cuantil_critico(costos: pd.DataFrame) -> pd.Series:
    c = costos.set_index("familia_id")
    return c.costo_faltante / (c.costo_faltante + c.costo_sobrante)


def cantidad_sugerida(venta_esperada, factor) -> np.ndarray:
    """Entero no negativo, tal como lo exige el contrato."""
    v = np.asarray(venta_esperada, float) * np.asarray(factor, float)
    return np.clip(np.round(np.nan_to_num(v)), 0, None).astype(int)


def calibrar_factores(
    familia: pd.Series, venta_esperada: pd.Series, real: pd.Series, costos: pd.DataFrame
) -> dict[str, float]:
    """Por familia, el factor de la grilla que minimiza el costo total en calibración."""
    c = costos.set_index("familia_id")
    df = pd.DataFrame({"familia": familia.values, "pred": venta_esperada.values, "real": real.values})
    factores: dict[str, float] = {}
    for fam, g in df.groupby("familia"):
        cf, cs = c.loc[fam, "costo_faltante"], c.loc[fam, "costo_sobrante"]
        sug = np.clip(np.round(np.outer(g.pred.values, GRILLA_FACTORES)), 0, None)
        r = g.real.values[:, None]
        total = (cf * np.maximum(r - sug, 0) + cs * np.maximum(sug - r, 0)).sum(axis=0)
        factores[fam] = float(GRILLA_FACTORES[int(np.argmin(total))])
    return factores
