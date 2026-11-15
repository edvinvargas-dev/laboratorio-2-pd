"""Arranque del producto: datos publicados y primer modelo, una sola vez.

Lo ejecuta el servicio `arranque` del compose en cada `docker compose up`:
  1. espera la base del producto, aplica el esquema y carga el histórico (si falta);
  2. espera a MLflow;
  3. si no hay modelo con alias `vigente`, entrena, registra y promueve el primero.
Si todo eso ya existe (volúmenes conservados), termina en segundos sin repetir trabajo.
Si algo falla, sale con código ≠ 0 y Docker lo reintenta (restart: on-failure).

Uso:  python -m app.arranque
"""

from __future__ import annotations

import logging
import os
import sys
import time
import urllib.request

from app.dependencias import Config

log = logging.getLogger("arranque")


def esperar(descripcion: str, prueba, max_seg: int = 300, intervalo: int = 3):
    t0 = time.time()
    while True:
        try:
            resultado = prueba()
            log.info("%s: listo (%.0f s)", descripcion, time.time() - t0)
            return resultado
        except Exception as e:
            if time.time() - t0 > max_seg:
                raise RuntimeError(f"{descripcion}: no disponible tras {max_seg} s ({e})") from e
            time.sleep(intervalo)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = Config.desde_entorno()
    if not cfg.database_url or not cfg.mlflow_uri:
        log.error("faltan DATABASE_URL/APP_DB_* o MLFLOW_TRACKING_URI")
        return 2

    # 1. Base de datos: esquema + histórico (idempotente)
    from app.servicios.repositorio_pg import RepositorioPostgres

    repo = RepositorioPostgres(cfg.database_url, esquema=cfg.esquema_sql)
    cargado = esperar("base de datos", lambda: repo.inicializar(cfg.data_dir))
    log.info("histórico %s", "cargado ahora" if cargado else "ya estaba cargado")
    repo.cerrar()

    # 2. MLflow
    esperar("MLflow", lambda: urllib.request.urlopen(f"{cfg.mlflow_uri.rstrip('/')}/health", timeout=5))

    # 3. Primer modelo (solo si no hay vigente)
    from ml import registro

    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "30")
    import mlflow

    mlflow.set_tracking_uri(cfg.mlflow_uri)
    from mlflow import MlflowClient
    from mlflow.exceptions import MlflowException

    try:
        mv = MlflowClient().get_model_version_by_alias(registro.NOMBRE_MODELO, registro.ALIAS_VIGENTE)
        log.info("ya hay modelo vigente (versión %s): no se entrena", mv.version)
        return 0
    except MlflowException as e:
        if "RESOURCE_DOES_NOT_EXIST" not in str(e.error_code) and "not found" not in str(e).lower():
            raise
    log.info("no hay modelo vigente: se entrena el primero")

    from ml.pipeline import ejecutar

    resultado = ejecutar(cfg.data_dir, cfg.database_url, {"origen": "arranque"})
    log.info("resultado: %s", resultado)
    return 0 if resultado.get("promovido") else 1


if __name__ == "__main__":
    sys.exit(main())
