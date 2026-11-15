"""Modelos Pydantic del contrato (Anexo del enunciado).

Dos grupos:
- Solicitudes *limpias*: lo que queda después de pasar por `limpieza/`. La entrada
  cruda no se valida directamente con estos modelos porque un 422 genérico de
  Pydantic impediría reparar o advertir; la limpieza decide primero.
- Respuestas: exactamente los campos del contrato (se pueden agregar, nunca quitar).
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ----------------------------------------------------------------- calidad


class ObservacionCalidad(BaseModel):
    campo: str
    accion: Literal["reparar", "advertir"]
    detalle: str


def estado_calidad(observaciones: list[ObservacionCalidad]) -> str:
    """El estado se deriva de las acciones: advertir > reparar > ok."""
    acciones = {o.accion for o in observaciones}
    return "advertencia" if "advertir" in acciones else "corregido" if acciones else "ok"


class Calidad(BaseModel):
    estado: Literal["ok", "corregido", "advertencia"]
    observaciones: list[ObservacionCalidad] = Field(default_factory=list)

    @classmethod
    def desde(cls, observaciones: list[ObservacionCalidad]) -> "Calidad":
        return cls(estado=estado_calidad(observaciones), observaciones=observaciones)

    @model_validator(mode="after")
    def _coherente(self) -> "Calidad":
        esperado = estado_calidad(self.observaciones)
        if self.estado != esperado:
            raise ValueError(f"estado {self.estado!r} incoherente con las observaciones (debería ser {esperado!r})")
        return self


# ------------------------------------------------------- solicitudes limpias


class FamiliaPromo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    familia_id: str
    en_promocion: int = Field(ge=0)


class SolicitudPrediccion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tienda_id: int
    fecha: dt.date
    familias: list[FamiliaPromo] = Field(min_length=1)


class VentaFamilia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    familia_id: str
    ventas: int = Field(ge=0)


class SolicitudObservacion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tienda_id: int
    fecha: dt.date
    ventas: list[VentaFamilia] = Field(min_length=1)


# ---------------------------------------------------------------- respuestas


class PrediccionFamilia(BaseModel):
    familia_id: str
    venta_esperada: float
    cantidad_sugerida: int = Field(ge=0)


class RespuestaPrediccion(BaseModel):
    tienda_id: int
    fecha: dt.date
    version_modelo: str
    predicciones: list[PrediccionFamilia]
    calidad: Calidad


class RespuestaObservacion(BaseModel):
    registros_guardados: int = Field(ge=0)
    calidad: Calidad


class RespuestaReentrenarInicio(BaseModel):
    id: str


class RespuestaReentrenarEstado(BaseModel):
    model_config = ConfigDict(extra="allow")
    estado: Literal["en_curso", "exitoso", "fallido"]
    promovido: bool | None = None
    version: str | None = None
    motivo: str | None = None


class RespuestaModelo(BaseModel):
    nombre: str
    alias: str
    version: str


class RespuestaHealth(BaseModel):
    model_config = ConfigDict(extra="allow")
    estado: Literal["ok", "degradado"]
    motivo: str | None = None
