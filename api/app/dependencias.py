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


@dataclass
class Config:
    data_dir: str = os.getenv("DATA_DIR", "data")
    modelo_nombre: str = os.getenv("MODELO_NOMBRE", "novamercado-pronostico")
    modelo_alias: str = os.getenv("MODELO_ALIAS", "vigente")
    modelo_archivo: str | None = os.getenv("MODELO_ARCHIVO")  # solo desarrollo local


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


def construir_dependencias(cfg: Config | None = None) -> Dependencias:
    """Desarrollo local (fase 2): repositorio en memoria con el histórico y modelo en pickle."""
    cfg = cfg or Config()
    cat = cargar_catalogos(cfg.data_dir)
    gestor = (
        GestorModeloArchivo(cfg.modelo_archivo, cfg.modelo_nombre, cfg.modelo_alias)
        if cfg.modelo_archivo else GestorModeloFijo(None)
    )
    return Dependencias(
        cat=cat, gestor=gestor,
        repo=RepositorioMemoria(cargar_historico(cfg.data_dir)),
        orquestador=OrquestadorFalso(),
    )
