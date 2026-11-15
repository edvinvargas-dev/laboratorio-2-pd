"""Persistencia de la operación: solicitudes, predicciones, correcciones y observaciones.

- RepositorioMemoria: todo en memoria (pruebas y desarrollo local).
- (fase 4) RepositorioPostgres: la base de datos propia del producto.
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any, Protocol

import pandas as pd

from app.schemas import Calidad, RespuestaPrediccion, SolicitudObservacion, SolicitudPrediccion

COLUMNAS_HISTORIA = ["fecha", "tienda_id", "familia_id", "ventas"]


class Repositorio(Protocol):
    def ping(self) -> bool: ...

    def historia(self, tienda_id: int, desde: dt.date, hasta: dt.date) -> pd.DataFrame:
        """Ventas conocidas de la tienda con desde <= fecha < hasta."""

    def registrar_prediccion(self, crudo: Any, solicitud: SolicitudPrediccion, respuesta: RespuestaPrediccion) -> None: ...

    def registrar_rechazo(self, endpoint: str, crudo: Any, detalle: str) -> None: ...

    def guardar_observacion(self, crudo: Any, solicitud: SolicitudObservacion, calidad: Calidad) -> int:
        """Guarda las ventas reales; devuelve cuántos registros son nuevos o cambiaron."""


class RepositorioMemoria:
    def __init__(self, historico: pd.DataFrame | None = None):
        self._lock = threading.Lock()
        self.ventas: dict[tuple[int, dt.date, str], int] = {}
        if historico is not None and len(historico):
            for r in historico[COLUMNAS_HISTORIA].itertuples(index=False):
                self.ventas[(int(r.tienda_id), pd.Timestamp(r.fecha).date(), r.familia_id)] = int(r.ventas)
        self.predicciones: list[dict] = []
        self.rechazos: list[dict] = []
        self.solicitudes_observacion: list[dict] = []

    def ping(self) -> bool:
        return True

    def historia(self, tienda_id: int, desde: dt.date, hasta: dt.date) -> pd.DataFrame:
        filas = [
            (f, t, fam, v) for (t, f, fam), v in self.ventas.items() if t == tienda_id and desde <= f < hasta
        ]
        df = pd.DataFrame(filas, columns=COLUMNAS_HISTORIA)
        df["fecha"] = pd.to_datetime(df["fecha"])
        return df

    def registrar_prediccion(self, crudo, solicitud, respuesta) -> None:
        with self._lock:
            self.predicciones.append({"crudo": crudo, "solicitud": solicitud, "respuesta": respuesta})

    def registrar_rechazo(self, endpoint, crudo, detalle) -> None:
        with self._lock:
            self.rechazos.append({"endpoint": endpoint, "crudo": crudo, "detalle": detalle})

    def guardar_observacion(self, crudo, solicitud, calidad) -> int:
        cambios = 0
        with self._lock:
            self.solicitudes_observacion.append({"crudo": crudo, "solicitud": solicitud, "calidad": calidad})
            for v in solicitud.ventas:
                clave = (solicitud.tienda_id, solicitud.fecha, v.familia_id)
                if self.ventas.get(clave) != v.ventas:
                    self.ventas[clave] = v.ventas
                    cambios += 1
        return cambios
