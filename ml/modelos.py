"""Modelos de pronóstico y el objeto que se despliega (Pronosticador).

- ModeloBaseline: mediana de las ventas del mismo día de la semana en las 4 semanas
  previas. Sin entrenamiento; es la vara mínima que el modelo de ML debe superar.
- ModeloLGBM: gradient boosting (LightGBM) con objetivo Poisson, adecuado para
  conteos no negativos con escalas muy distintas entre tiendas y familias.
- Pronosticador: modelo + factores de cantidad sugerida por familia. Es lo que se
  registra en MLflow y lo que carga la API.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.costos import cantidad_sugerida
from ml.features import CATEGORICAS, FEATURES


class ModeloBaseline:
    nombre = "baseline_mismo_dia_4sem"

    def fit(self, X: pd.DataFrame, y: pd.Series, **_) -> "ModeloBaseline":
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        p = X["mismo_dia_mediana"].fillna(X["media_28"]).fillna(0.0)
        return p.to_numpy(float)


class ModeloLGBM:
    nombre = "lgbm_poisson"

    PARAMS = dict(
        objective="poisson",
        learning_rate=0.05,
        num_leaves=63,
        min_data_in_leaf=40,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=1,
        lambda_l2=1.0,
        verbose=-1,
        seed=42,
    )

    def __init__(self, n_iter: int = 2000, params: dict | None = None):
        self.n_iter = n_iter
        self.params = {**self.PARAMS, **(params or {})}
        self.booster: lgb.Booster | None = None

    def _dataset(self, X, y=None, ref=None):
        return lgb.Dataset(X[FEATURES], label=y, categorical_feature=CATEGORICAS, reference=ref, free_raw_data=False)

    def fit(self, X, y, X_val=None, y_val=None) -> "ModeloLGBM":
        dtrain = self._dataset(X, y)
        if X_val is not None:
            dval = self._dataset(X_val, y_val, ref=dtrain)
            self.booster = lgb.train(
                self.params, dtrain, self.n_iter, valid_sets=[dval],
                callbacks=[lgb.early_stopping(100, verbose=False)],
            )
            self.n_iter = self.booster.best_iteration
        else:
            self.booster = lgb.train(self.params, dtrain, self.n_iter)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.booster.predict(X[FEATURES], num_iteration=self.n_iter)

    def importancia(self) -> pd.Series:
        imp = self.booster.feature_importance("gain")
        return pd.Series(imp, index=self.booster.feature_name()).sort_values(ascending=False)


@dataclass
class Pronosticador:
    """Lo que se despliega: pronóstico puntual + factor de cantidad sugerida por familia."""

    modelo: ModeloBaseline | ModeloLGBM
    factores: dict[str, float]
    info: dict = field(default_factory=dict)  # fechas de corte, métricas, etc.

    def predecir(self, X: pd.DataFrame) -> pd.DataFrame:
        venta = np.clip(self.modelo.predict(X), 0, None)
        factor = X["familia_id"].map(self.factores).fillna(1.0).to_numpy()
        return pd.DataFrame(
            {
                "familia_id": X["familia_id"].to_numpy(),
                "venta_esperada": np.round(venta, 1),
                "cantidad_sugerida": cantidad_sugerida(venta, factor),
            },
            index=X.index,
        )
