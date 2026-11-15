"""Configuración por variables de entorno y armado de las dependencias del servicio."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.limpieza import Contexto
from app.limpieza.contexto import contexto_desde_catalogos
from app.servicios.modelo import GestorModelo, GestorModeloArchivo, GestorModeloFijo
from app.servicios.orquestador import Orquestador, OrquestadorFalso
from app.servicios.repositorio import Repositorio, RepositorioMemoria
from ml.catalogos import Catalogos, cargar_catalogos, cargar_historico


def cargar_archivo_env(ruta: str | None) -> None:
    """Desarrollo local: carga un archivo .env sin pisar variables ya definidas."""
    if not ruta or not os.path.exists(ruta):
        return
    for linea in open(ruta, encoding="utf-8"):
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _url_base_datos() -> str | None:
    """DATABASE_URL explícita, o armada con las variables APP_DB_* (las mismas del compose)."""
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if not os.getenv("APP_DB_USER"):
        return None
    return (f"postgresql://{os.environ['APP_DB_USER']}:{os.environ['APP_DB_PASSWORD']}"
            f"@{os.getenv('APP_DB_HOST', 'db')}:{os.getenv('APP_DB_PORT', '5432')}/{os.environ['APP_DB_NAME']}")


@dataclass
class Config:
    data_dir: str = "data"
    modelo_nombre: str = "novamercado-pronostico"
    modelo_alias: str = "vigente"
    modelo_archivo: str | None = None  # solo desarrollo local
    database_url: str | None = None  # sin ella: repositorio en memoria
    esquema_sql: str | None = None
    mlflow_uri: str | None = None  # con ella: el modelo sigue el alias del Model Registry
    cache_modelo: str = "cache_modelo"
    intervalo_modelo: float = 15.0

    @classmethod
    def desde_entorno(cls) -> "Config":
        cargar_archivo_env(os.getenv("ENV_FILE"))
        return cls(
            data_dir=os.getenv("DATA_DIR", "data"),
            modelo_nombre=os.getenv("MODELO_NOMBRE", "novamercado-pronostico"),
            modelo_alias=os.getenv("MODELO_ALIAS", "vigente"),
            modelo_archivo=os.getenv("MODELO_ARCHIVO"),
            database_url=_url_base_datos(),
            esquema_sql=os.getenv("ESQUEMA_SQL"),
            mlflow_uri=os.getenv("MLFLOW_TRACKING_URI"),
            cache_modelo=os.getenv("CACHE_MODELO", "cache_modelo"),
            intervalo_modelo=float(os.getenv("INTERVALO_MODELO_SEG", "15")),
        )


@dataclass
class Dependencias:
    cat: Catalogos
    gestor: GestorModelo
    repo: Repositorio
    orquestador: Orquestador

    @property
    def contexto(self) -> Contexto:
        if getattr(self, "_contexto", None) is None:
            self._contexto = contexto_desde_catalogos(self.cat)
        return self._contexto


def construir_repositorio(cfg: Config) -> Repositorio:
    if not cfg.database_url:
        return RepositorioMemoria(cargar_historico(cfg.data_dir))
    from app.servicios.repositorio_pg import RepositorioPostgres

    repo = RepositorioPostgres(cfg.database_url, esquema=cfg.esquema_sql)
    repo.inicializar(cfg.data_dir)  # esquema + histórico, solo la primera vez
    return repo


def construir_dependencias(cfg: Config | None = None) -> Dependencias:
    cfg = cfg or Config.desde_entorno()
    cat = cargar_catalogos(cfg.data_dir)
    return Dependencias(cat=cat, gestor=construir_gestor(cfg), repo=construir_repositorio(cfg),
                        orquestador=OrquestadorFalso())


def construir_gestor(cfg: Config) -> GestorModelo:
    if cfg.mlflow_uri:
        from app.servicios.modelo_mlflow import FuenteMLflow, GestorModeloMLflow

        fuente = FuenteMLflow(cfg.mlflow_uri, cfg.modelo_nombre, cfg.modelo_alias)
        return GestorModeloMLflow(fuente, cfg.modelo_nombre, cfg.modelo_alias, cfg.cache_modelo,
                                  cfg.intervalo_modelo).iniciar()
    if cfg.modelo_archivo:
        return GestorModeloArchivo(cfg.modelo_archivo, cfg.modelo_nombre, cfg.modelo_alias)
    return GestorModeloFijo(None)
