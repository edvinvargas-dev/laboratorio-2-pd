"""Registro de experimentos y modelos en MLflow.

- Cada entrenamiento es un run del experimento `novamercado-pronostico` con parámetros,
  métricas técnicas y de costo, factores, importancias y datos usados (linaje).
- El modelo se registra como pyfunc con el Pronosticador serializado como artefacto.
- El modelo vigente es el que tiene el alias `vigente`; el anterior conserva `anterior`.
"""

from __future__ import annotations

import json
import os
import pickle
import tempfile
from dataclasses import dataclass
from pathlib import Path

import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from ml.modelos import Pronosticador

EXPERIMENTO = "novamercado-pronostico"
NOMBRE_MODELO = os.getenv("MODELO_NOMBRE", "novamercado-pronostico")
ALIAS_VIGENTE = os.getenv("MODELO_ALIAS", "vigente")
ALIAS_ANTERIOR = "anterior"
ARTEFACTO = "pronosticador.pkl"
RAIZ_ML = Path(__file__).resolve().parent


class PyfuncPronosticador(mlflow.pyfunc.PythonModel):
    """Envoltura pyfunc: recibe el DataFrame de features y devuelve venta y cantidad sugerida."""

    def load_context(self, context):
        with open(context.artifacts["pronosticador"], "rb") as f:
            self.pronosticador = pickle.load(f)

    def predict(self, context, model_input, params=None):
        return self.pronosticador.predecir(model_input)


@dataclass
class ModeloRegistrado:
    pronosticador: Pronosticador
    version: str


def cliente() -> MlflowClient:
    return MlflowClient()


def cargar_por_alias(alias: str = ALIAS_VIGENTE, nombre: str = NOMBRE_MODELO) -> ModeloRegistrado | None:
    """El modelo con ese alias, o None si todavía no existe ninguno."""
    c = cliente()
    try:
        mv = c.get_model_version_by_alias(nombre, alias)
    except MlflowException as e:
        if "RESOURCE_DOES_NOT_EXIST" in str(e.error_code) or "not found" in str(e).lower():
            return None
        raise
    return ModeloRegistrado(descargar_pronosticador(nombre, mv.version), str(mv.version))


def descargar_pronosticador(nombre: str, version: str, destino: str | Path | None = None) -> Pronosticador:
    destino = Path(destino or tempfile.mkdtemp(prefix="modelo_"))
    ruta = mlflow.artifacts.download_artifacts(artifact_uri=f"models:/{nombre}/{version}", dst_path=str(destino))
    with open(Path(ruta) / "artifacts" / ARTEFACTO, "rb") as f:
        return pickle.load(f)


def registrar_candidato(
    pron: Pronosticador,
    metricas: dict,
    metricas_extra: dict,
    datos: pd.DataFrame,
    etiquetas: dict,
    nombre: str = NOMBRE_MODELO,
) -> tuple[str, str]:
    """Registra el run y una nueva versión del modelo. Devuelve (run_id, versión). NO cambia alias."""
    mlflow.set_experiment(EXPERIMENTO)
    with mlflow.start_run(run_name=f"{pron.info.get('tipo', 'modelo')}_{pron.info.get('datos_hasta')}") as run:
        mlflow.set_tags(etiquetas)
        mlflow.log_params({k: v for k, v in pron.info.items() if not isinstance(v, (dict, list))})
        if hasattr(pron.modelo, "params"):
            mlflow.log_params({f"lgbm_{k}": v for k, v in pron.modelo.params.items()})
        mlflow.log_metrics({k: float(v) for k, v in metricas.items() if isinstance(v, (int, float))})
        mlflow.log_metrics({k: float(v) for k, v in metricas_extra.items() if v is not None})
        mlflow.log_metrics({f"costo_{k}": float(v) for k, v in metricas.get("costo_por_familia", {}).items()})
        mlflow.log_dict(pron.factores, "factores_cantidad_sugerida.json")

        # Linaje de datos: qué se usó para entrenar
        resumen = {
            "filas": int(len(datos)),
            "desde": str(datos.fecha.min().date()),
            "hasta": str(datos.fecha.max().date()),
            "filas_por_origen": datos["origen"].value_counts().to_dict() if "origen" in datos else {},
            "promocion_desconocida": int(datos.en_promocion.isna().sum()),
        }
        mlflow.log_dict(resumen, "datos_entrenamiento.json")
        mlflow.log_input(mlflow.data.from_pandas(datos.drop(columns=["origen"], errors="ignore").head(0),
                                                 name="ventas_entrenamiento"), context="entrenamiento")
        if hasattr(pron.modelo, "importancia"):
            imp = pron.modelo.importancia()
            mlflow.log_dict({k: float(v) for k, v in imp.items()}, "importancia_features.json")

        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / ARTEFACTO
            pkl.write_bytes(pickle.dumps(pron))
            info = mlflow.pyfunc.log_model(
                name="modelo",
                python_model=PyfuncPronosticador(),
                artifacts={"pronosticador": str(pkl)},
                code_paths=[str(RAIZ_ML)],
                pip_requirements=["pandas", "numpy", "lightgbm"],
                registered_model_name=nombre,
            )
        version = str(info.registered_model_version)
        cliente().set_model_version_tag(nombre, version, "datos_hasta", pron.info.get("datos_hasta", ""))
        return run.info.run_id, version


def promover(version: str, motivo: str, version_anterior: str | None, nombre: str = NOMBRE_MODELO) -> None:
    """Mueve el alias vigente a `version` (último paso: si algo falla antes, el vigente no cambia)."""
    c = cliente()
    if version_anterior:
        c.set_registered_model_alias(nombre, ALIAS_ANTERIOR, version_anterior)
    c.set_registered_model_alias(nombre, ALIAS_VIGENTE, version)
    c.set_model_version_tag(nombre, version, "motivo_promocion", motivo)


def anotar_decision(version: str, promovido: bool, motivo: str, run_id: str, nombre: str = NOMBRE_MODELO) -> None:
    c = cliente()
    c.set_model_version_tag(nombre, version, "promovido", str(promovido).lower())
    c.set_model_version_tag(nombre, version, "motivo", motivo)
    c.set_tag(run_id, "promovido", str(promovido).lower())
    c.set_tag(run_id, "motivo", motivo)
    c.update_model_version(nombre, version, description=motivo)


def resumen_json(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)
