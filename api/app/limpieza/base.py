"""Piezas comunes de la limpieza: el rechazo, la bitácora de acciones y el contexto."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from app.schemas import ObservacionCalidad


class Rechazo(Exception):
    """La solicitud no se puede atender: se responde 422 con `detail`."""

    def __init__(self, detalle: str):
        super().__init__(detalle)
        self.detalle = detalle


@dataclass
class Bitacora:
    """Acumula lo que la limpieza hizo con cada campo, para el bloque `calidad`."""

    observaciones: list[ObservacionCalidad] = field(default_factory=list)

    def reparar(self, campo: str, detalle: str) -> None:
        self.observaciones.append(ObservacionCalidad(campo=campo, accion="reparar", detalle=detalle))

    def advertir(self, campo: str, detalle: str) -> None:
        self.observaciones.append(ObservacionCalidad(campo=campo, accion="advertir", detalle=detalle))


@dataclass(frozen=True)
class Contexto:
    """Lo que la limpieza necesita saber del negocio (sale de los catálogos).

    No hay reloj: el rango de fechas válido se deriva de los datos (calendario de feriados).
    """

    apertura: dict[int, dt.date]  # tienda_id → fecha de apertura
    nombres_tienda: dict[str, int]  # clave normalizada del nombre → tienda_id (solo nombres únicos)
    familias: dict[str, str]  # familia_id → nombre
    calendario_hasta: dt.date  # última fecha cubierta por feriados.csv
    fecha_min: dt.date  # fuera de [fecha_min, fecha_max] la fecha se considera absurda
    fecha_max: dt.date

    @property
    def tiendas(self) -> frozenset[int]:
        return frozenset(self.apertura)
