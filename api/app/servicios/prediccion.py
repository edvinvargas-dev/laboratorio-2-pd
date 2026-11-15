"""De una solicitud limpia a predicciones, usando solo ventas anteriores a la fecha."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from app.schemas import ObservacionCalidad, PrediccionFamilia, SolicitudPrediccion
from app.servicios.modelo import ModeloCargado
from app.servicios.repositorio import Repositorio
from ml.catalogos import Catalogos
from ml.features import VENTANA_MAX, construir_features


def predecir(
    sol: SolicitudPrediccion, modelo: ModeloCargado, repo: Repositorio, cat: Catalogos
) -> tuple[list[PrediccionFamilia], list[ObservacionCalidad]]:
    """Predicciones y advertencias sobre la historia disponible (no inventa ventas faltantes)."""
    desde = sol.fecha - dt.timedelta(days=VENTANA_MAX)
    historia = repo.historia(sol.tienda_id, desde, sol.fecha)  # fecha < sol.fecha
    objetivos = pd.DataFrame(
        {
            "fecha": pd.Timestamp(sol.fecha),
            "tienda_id": sol.tienda_id,
            "familia_id": [f.familia_id for f in sol.familias],
            "en_promocion": [f.en_promocion for f in sol.familias],
        }
    )
    X = construir_features(historia, objetivos, cat)
    salida = modelo.pronosticador.predecir(X)

    obs: list[ObservacionCalidad] = []
    sin_nada = X.familia_id[X.media_28.isna()].tolist()
    sin_ayer = X.familia_id[X.lag_1.isna() & X.media_28.notna()].tolist()
    if sin_nada:
        obs.append(ObservacionCalidad(
            campo="familias", accion="advertir",
            detalle=f"sin ventas registradas en los {VENTANA_MAX} días previos para {sin_nada}; "
                    "el pronóstico usa solo calendario y promociones"))
    if sin_ayer:
        obs.append(ObservacionCalidad(
            campo="familias", accion="advertir",
            detalle=f"falta la venta del día anterior para {sin_ayer}; se usó la historia disponible"))

    predicciones = [
        PrediccionFamilia(familia_id=r.familia_id, venta_esperada=float(r.venta_esperada),
                          cantidad_sugerida=int(r.cantidad_sugerida))
        for r in salida.itertuples(index=False)
    ]
    return predicciones, obs
