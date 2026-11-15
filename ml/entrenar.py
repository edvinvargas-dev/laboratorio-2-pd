"""Entrenamiento y evaluación de un candidato.

Partición temporal (sin barajar: es una serie de tiempo):

    |────────── entrenamiento ──────────|── calibración ──|──── prueba ────|
                                          28 días           28 días (últimos)

1. El modelo se ajusta con *entrenamiento* (LightGBM usa *calibración* para early stopping).
2. Los factores de cantidad sugerida se eligen en *calibración* (minimizan el costo).
3. Las métricas se reportan en *prueba*, que nada de lo anterior vio.
4. Si `reajustar=True`, el modelo final se vuelve a entrenar con TODOS los datos y el
   mismo número de iteraciones: es el que se despliega, aprovechando la info más reciente.

Uso:  .venv\\Scripts\\python -m ml.entrenar --data data
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.catalogos import Catalogos, cargar_catalogos, cargar_historico
from ml.costos import calibrar_factores, cantidad_sugerida, costo, cuantil_critico
from ml.features import construir_features
from ml.modelos import ModeloBaseline, ModeloLGBM, Pronosticador

DIAS_PRUEBA = 28
DIAS_CALIBRACION = 28


def preparar_dataset(historia: pd.DataFrame, cat: Catalogos) -> tuple[pd.DataFrame, pd.Series]:
    """Features para cada fila del histórico; se descartan filas sin historia previa."""
    objetivos = historia[["fecha", "tienda_id", "familia_id", "en_promocion"]]
    X = construir_features(historia, objetivos, cat)
    X["ventas"] = historia["ventas"].to_numpy()
    X = X[X.media_28.notna()].reset_index(drop=True)
    return X, X.pop("ventas").astype(float)


def evaluar(pred: pd.DataFrame, real: pd.Series, costos: pd.DataFrame) -> dict:
    c = costos.set_index("familia_id")
    cf = pred.familia_id.map(c.costo_faltante).to_numpy()
    cs = pred.familia_id.map(c.costo_sobrante).to_numpy()
    r = real.to_numpy(float)
    v = pred.venta_esperada.to_numpy(float)
    err = v - r
    costo_sug = costo(r, pred.cantidad_sugerida, cf, cs)
    costo_puro = costo(r, cantidad_sugerida(v, 1.0), cf, cs)
    por_familia = pd.Series(costo_sug, index=pred.familia_id.to_numpy()).groupby(level=0).sum()
    return {
        "mae": float(np.abs(err).mean()),
        "rmse": float(np.sqrt((err**2).mean())),
        "wape": float(np.abs(err).sum() / r.sum()),
        "sesgo": float(err.sum() / r.sum()),
        "costo": float(costo_sug.sum()),
        "costo_sin_ajuste": float(costo_puro.sum()),
        "costo_por_familia": por_familia.round(1).to_dict(),
    }


@dataclass
class Resultado:
    pronosticador: Pronosticador  # el que se despliega
    metricas_prueba: dict
    modelo_eval: object  # modelo entrenado sin calibración/prueba (para importancias)
    X_prueba: pd.DataFrame | None = None  # para evaluar otros modelos sobre los mismos días
    y_prueba: pd.Series | None = None


def crear_modelo(tipo: str, **kw):
    return {"baseline": ModeloBaseline, "lgbm": ModeloLGBM}[tipo](**kw)


def entrenar_candidato(
    historia: pd.DataFrame,
    cat: Catalogos,
    tipo: str = "lgbm",
    dias_prueba: int = DIAS_PRUEBA,
    dias_calibracion: int = DIAS_CALIBRACION,
    reajustar: bool = True,
    inicio_prueba: pd.Timestamp | None = None,
    datos: tuple[pd.DataFrame, pd.Series] | None = None,
) -> Resultado:
    """`inicio_prueba` fija el primer día de la ventana de prueba (por defecto, los últimos
    `dias_prueba` días). `datos` permite reutilizar un dataset ya preparado."""
    X, y = datos if datos is not None else preparar_dataset(historia, cat)
    fin = X.fecha.max()
    ini_prueba = pd.Timestamp(inicio_prueba) if inicio_prueba is not None else fin - pd.Timedelta(days=dias_prueba - 1)
    ini_calib = ini_prueba - pd.Timedelta(days=dias_calibracion)
    tr = X.fecha < ini_calib
    ca = (X.fecha >= ini_calib) & (X.fecha < ini_prueba)
    te = X.fecha >= ini_prueba

    modelo = crear_modelo(tipo)
    modelo.fit(X[tr], y[tr], X_val=X[ca], y_val=y[ca])
    factores = calibrar_factores(X.familia_id[ca], pd.Series(modelo.predict(X[ca])), y[ca], cat.costos)
    metricas = evaluar(Pronosticador(modelo, factores).predecir(X[te]), y[te], cat.costos)

    final = modelo
    if reajustar and tipo != "baseline":
        final = crear_modelo(tipo, n_iter=modelo.n_iter).fit(X, y)

    info = {
        "tipo": tipo,
        "datos_hasta": str(fin.date()),
        "inicio_calibracion": str(ini_calib.date()),
        "inicio_prueba": str(ini_prueba.date()),
        "n_filas": int(len(X)),
        "n_iter": int(getattr(modelo, "n_iter", 0)),
        "dias_prueba": int(X.fecha[te].nunique()),
    }
    return Resultado(Pronosticador(final, factores, info), metricas, modelo, X[te], y[te])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--guardar", help="ruta .pkl donde guardar el Pronosticador LightGBM (desarrollo local)")
    args = ap.parse_args()

    cat = cargar_catalogos(args.data)
    hist = cargar_historico(args.data)
    resultados = {}
    for tipo in ["baseline", "lgbm"]:
        t0 = time.time()
        resultados[tipo] = entrenar_candidato(hist, cat, tipo)
        print(f"[{tipo}] entrenado en {time.time() - t0:.1f}s")

    info = resultados["lgbm"].pronosticador.info
    print(f"\nPrueba: {info['inicio_prueba']} → {info['datos_hasta']}  (calibración desde {info['inicio_calibracion']})")
    tabla = pd.DataFrame({k: {m: v for m, v in r.metricas_prueba.items() if m != "costo_por_familia"}
                          for k, r in resultados.items()}).T
    print(tabla.round(3).to_string())
    mejora = 1 - tabla.loc["lgbm", "costo"] / tabla.loc["baseline", "costo"]
    print(f"\nLightGBM reduce el costo {mejora:.1%} frente al baseline")

    fam = pd.DataFrame({
        "q_critico": cuantil_critico(cat.costos).round(3),
        "factor_lgbm": pd.Series(resultados["lgbm"].pronosticador.factores),
        "costo_base": pd.Series(resultados["baseline"].metricas_prueba["costo_por_familia"]),
        "costo_lgbm": pd.Series(resultados["lgbm"].metricas_prueba["costo_por_familia"]),
    }).sort_values("q_critico")
    print("\nPor familia:\n", fam.to_string())
    print("\nImportancia (gain) top 15:\n", (resultados["lgbm"].modelo_eval.importancia().head(15) / 1e6).round(2).to_string())

    if args.guardar:
        import pickle
        from pathlib import Path

        Path(args.guardar).parent.mkdir(parents=True, exist_ok=True)
        with open(args.guardar, "wb") as f:
            pickle.dump(resultados["lgbm"].pronosticador, f)
        print(f"\nPronosticador guardado en {args.guardar}")


if __name__ == "__main__":
    main()
