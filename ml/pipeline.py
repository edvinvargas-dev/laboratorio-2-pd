"""Ciclo completo de reentrenamiento: datos → candidato → comparación → registro → promoción.

Lo ejecutan el DAG de Airflow y el arranque inicial (cuando aún no hay modelo).
Uso:  python -m ml.pipeline [--data data]
Variables: MLFLOW_TRACKING_URI, DATABASE_URL (opcional; sin ella usa el CSV), DATA_DIR.

Garantía: el alias `vigente` se mueve solo en el último paso y solo si el criterio lo
aprueba. Cualquier fallo antes deja intacto el modelo vigente.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time

import numpy as np
import pandas as pd

from ml import registro
from ml.catalogos import cargar_catalogos
from ml.criterio import DIAS_MINIMOS, Evaluacion, decidir
from ml.datos import cargar_datos_entrenamiento
from ml.entrenar import DIAS_PRUEBA, entrenar_candidato, evaluar, preparar_dataset

log = logging.getLogger("pipeline")


def _ventana(fin: pd.Timestamp, vigente: registro.ModeloRegistrado | None) -> tuple[pd.Timestamp, int]:
    """Primer día de la ventana de evaluación y cuántos días nuevos hay desde el vigente."""
    defecto = fin - pd.Timedelta(days=DIAS_PRUEBA - 1)
    if vigente is None:
        return defecto, DIAS_PRUEBA
    corte = pd.Timestamp(vigente.pronosticador.info.get("datos_hasta", "1900-01-01"))
    nuevos = int((fin - corte).days)
    return max(corte + pd.Timedelta(days=1), defecto), nuevos


def ejecutar(data_dir: str, database_url: str | None = None, etiquetas: dict | None = None) -> dict:
    t0 = time.time()
    cat = cargar_catalogos(data_dir)
    datos = cargar_datos_entrenamiento(database_url, data_dir)
    vigente = registro.cargar_por_alias()  # si MLflow no responde, falla aquí: nada cambia
    version_vigente = vigente.version if vigente else None
    fin = datos.fecha.max()
    inicio, dias_nuevos = _ventana(fin, vigente)
    log.info("datos hasta %s (%d filas); vigente=%s; días nuevos=%d", fin.date(), len(datos), version_vigente, dias_nuevos)

    if vigente is not None and dias_nuevos < DIAS_MINIMOS:
        return {"estado": "exitoso", "promovido": False, "version": version_vigente,
                "motivo": f"Solo {dias_nuevos} días nuevos desde el vigente (versión {version_vigente}); "
                          f"se necesitan {DIAS_MINIMOS} para comparar. No se entrenó."}

    dataset = preparar_dataset(datos, cat)
    cand = entrenar_candidato(datos, cat, "lgbm", inicio_prueba=inicio, datos=dataset)
    base = entrenar_candidato(datos, cat, "baseline", inicio_prueba=inicio, datos=dataset)

    costo_vigente = None
    if vigente is not None:
        try:
            costo_vigente = evaluar(vigente.pronosticador.predecir(cand.X_prueba), cand.y_prueba, cat.costos)["costo"]
        except Exception as e:  # p. ej. el vigente usa otras features
            log.warning("no se pudo evaluar el vigente: %s", e)

    sug = cand.pronosticador.predecir(cand.X_prueba).cantidad_sugerida
    valido = bool(np.isfinite(cand.metricas_prueba["costo"]) and (sug >= 0).all())
    ev = Evaluacion(
        costo_candidato=cand.metricas_prueba["costo"], costo_baseline=base.metricas_prueba["costo"],
        costo_vigente=costo_vigente, dias_evaluacion=cand.pronosticador.info["dias_prueba"],
        version_vigente=version_vigente, candidato_valido=valido,
    )
    decision = decidir(ev)
    log.info("decisión: %s — %s", decision.promover, decision.motivo)

    extra = {"costo_baseline": ev.costo_baseline, "costo_vigente": costo_vigente,
             "dias_evaluacion": ev.dias_evaluacion, "dias_nuevos": dias_nuevos}
    tags = {"version_vigente_previa": str(version_vigente), **(etiquetas or {})}
    run_id, version = registro.registrar_candidato(cand.pronosticador, cand.metricas_prueba, extra, datos, tags)
    registro.anotar_decision(version, decision.promover, decision.motivo, run_id)
    if decision.promover:
        registro.promover(version, decision.motivo, version_vigente)  # último paso

    return {
        "estado": "exitoso",
        "promovido": decision.promover,
        "version": version if decision.promover else version_vigente,
        "motivo": decision.motivo,
        "version_candidata": version,
        "run_id": run_id,
        "segundos": round(time.time() - t0, 1),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.getenv("DATA_DIR", "data"))
    a = ap.parse_args()
    url = os.getenv("DATABASE_URL")
    print(json.dumps(ejecutar(a.data, url, {"origen": "cli"}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
