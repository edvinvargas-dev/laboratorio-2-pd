"""Disparo y consulta del reentrenamiento.

- OrquestadorFalso: responde de inmediato (pruebas y desarrollo local).
- (fase 6) OrquestadorAirflow: dispara el DAG por la API REST de Airflow.
"""

from __future__ import annotations

import uuid
from typing import Protocol


class NoDisponible(Exception):
    """No se pudo iniciar la ejecución (→ 503)."""


class Orquestador(Protocol):
    def ping(self) -> bool: ...

    def disparar(self) -> str: ...

    def estado(self, id_ejecucion: str) -> dict | None:
        """None si el id no existe (→ 404)."""


class OrquestadorFalso:
    def __init__(self, disponible: bool = True, version: str = "1"):
        self.disponible = disponible
        self.version = version
        self.ejecuciones: dict[str, dict] = {}

    def ping(self) -> bool:
        return self.disponible

    def disparar(self) -> str:
        if not self.disponible:
            raise NoDisponible("Orquestador no disponible")
        i = uuid.uuid4().hex
        self.ejecuciones[i] = {
            "estado": "exitoso", "promovido": False, "version": self.version,
            "motivo": "Orquestador falso: no se entrena",
        }
        return i

    def estado(self, id_ejecucion: str) -> dict | None:
        return self.ejecuciones.get(id_ejecucion)
