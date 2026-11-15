"""Gestor del modelo vigente que sigue el alias del Model Registry de MLflow.

- Cada `intervalo` segundos (15 s por defecto) revisa MLflow:
    · si no responde → `mlflow_disponible()` = False (health 'degradado' en < 1 min) y
      se sigue sirviendo con el modelo cargado;
    · si responde y el alias apunta a otra versión → la descarga y la cambia en caliente
      (el servicio usa el modelo nuevo segundos después de la promoción, sin reinicio).
- Cada modelo cargado se guarda en una caché local (volumen). Al arrancar se carga de
  ahí primero: si MLflow está caído al reiniciar, el servicio igual tiene modelo.

La comunicación con MLflow está aislada en `FuenteMLflow`; las pruebas usan una fuente falsa.
"""

from __future__ import annotations

import logging
import os
import pickle
import threading
import urllib.request
from pathlib import Path
from typing import Protocol

from app.servicios.modelo import ModeloCargado
from ml.modelos import Pronosticador

log = logging.getLogger("modelo")


class Fuente(Protocol):
    def ping(self) -> bool: ...

    def version_alias(self) -> str | None:
        """Versión a la que apunta el alias; None si no existe ninguna."""

    def descargar(self, version: str) -> Pronosticador: ...


class FuenteMLflow:
    def __init__(self, uri: str, nombre: str, alias: str, timeout: int = 5):
        # Sin reintentos largos: un MLflow caído debe detectarse rápido
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", str(timeout))
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
        import mlflow

        mlflow.set_tracking_uri(uri)
        self.uri, self.nombre, self.alias, self.timeout = uri.rstrip("/"), nombre, alias, timeout

    def ping(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.uri}/health", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def version_alias(self) -> str | None:
        from mlflow import MlflowClient
        from mlflow.exceptions import MlflowException

        try:
            return str(MlflowClient().get_model_version_by_alias(self.nombre, self.alias).version)
        except MlflowException as e:
            if "RESOURCE_DOES_NOT_EXIST" in str(e.error_code) or "not found" in str(e).lower():
                return None
            raise

    def descargar(self, version: str) -> Pronosticador:
        from ml.registro import descargar_pronosticador

        return descargar_pronosticador(self.nombre, version)


class GestorModeloMLflow:
    def __init__(self, fuente: Fuente, nombre: str, alias: str, cache_dir: str | Path, intervalo: float = 15):
        self.fuente, self.nombre, self.alias = fuente, nombre, alias
        self.cache = Path(cache_dir)
        self.intervalo = intervalo
        self._modelo: ModeloCargado | None = None
        self._mlflow_ok = False
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    # ------------------------------------------------------------ interfaz API

    def actual(self) -> ModeloCargado | None:
        return self._modelo

    def mlflow_disponible(self) -> bool:
        return self._mlflow_ok

    # --------------------------------------------------------------- ciclo

    def iniciar(self) -> "GestorModeloMLflow":
        self._cargar_cache()
        self._hilo = threading.Thread(target=self._bucle, name="sincronizar-modelo", daemon=True)
        self._hilo.start()
        return self

    def detener(self) -> None:
        self._parar.set()

    def _bucle(self) -> None:
        while not self._parar.is_set():
            self.sincronizar()
            self._parar.wait(self.intervalo)

    def sincronizar(self) -> None:
        """Una revisión: disponibilidad de MLflow y, si cambió el alias, recarga."""
        if not self.fuente.ping():
            if self._mlflow_ok:
                log.warning("MLflow no disponible; se sigue con la versión %s", self._version())
            self._mlflow_ok = False
            return
        try:
            version = self.fuente.version_alias()
        except Exception as e:
            log.warning("no se pudo consultar el alias: %s", e)
            self._mlflow_ok = False
            return
        self._mlflow_ok = True
        if version is None or version == self._version():
            return
        with self._lock:
            try:
                pron = self.fuente.descargar(version)
                self._guardar_cache(version, pron)
                self._modelo = ModeloCargado(pron, self.nombre, self.alias, version)
                log.info("modelo cargado: %s versión %s", self.nombre, version)
            except Exception as e:  # el modelo actual sigue en servicio
                log.error("no se pudo cargar la versión %s: %s", version, e)

    def _version(self) -> str | None:
        return self._modelo.version if self._modelo else None

    # --------------------------------------------------------------- caché

    def _guardar_cache(self, version: str, pron: Pronosticador) -> None:
        self.cache.mkdir(parents=True, exist_ok=True)
        tmp = self.cache / "modelo.pkl.tmp"
        tmp.write_bytes(pickle.dumps({"version": version, "pronosticador": pron}))
        os.replace(tmp, self.cache / "modelo.pkl")  # reemplazo atómico

    def _cargar_cache(self) -> None:
        archivo = self.cache / "modelo.pkl"
        if not archivo.exists():
            return
        try:
            d = pickle.loads(archivo.read_bytes())
            self._modelo = ModeloCargado(d["pronosticador"], self.nombre, self.alias, d["version"])
            log.info("modelo cargado desde caché: versión %s", d["version"])
        except Exception as e:
            log.error("caché de modelo ilegible: %s", e)
