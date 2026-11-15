"""Acceso al modelo vigente.

La API no sabe de dónde viene el modelo; solo pide `actual()`. Implementaciones:
- GestorModeloFijo: un modelo dado en memoria (pruebas y desarrollo local).
- GestorModeloArchivo: carga un Pronosticador desde un pickle local.
- (fase 5) GestorModeloMLflow: sigue el alias del Model Registry y recarga solo.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ml.modelos import Pronosticador


@dataclass(frozen=True)
class ModeloCargado:
    pronosticador: Pronosticador
    nombre: str
    alias: str
    version: str


class GestorModelo(Protocol):
    def actual(self) -> ModeloCargado | None: ...

    def mlflow_disponible(self) -> bool: ...


class GestorModeloFijo:
    def __init__(self, modelo: ModeloCargado | None, mlflow_ok: bool = True):
        self.modelo = modelo
        self.mlflow_ok = mlflow_ok

    def actual(self) -> ModeloCargado | None:
        return self.modelo

    def mlflow_disponible(self) -> bool:
        return self.mlflow_ok


class GestorModeloArchivo(GestorModeloFijo):
    def __init__(self, ruta: str | Path, nombre: str, alias: str):
        with open(ruta, "rb") as f:
            pron: Pronosticador = pickle.load(f)
        super().__init__(ModeloCargado(pron, nombre, alias, version="local"))
