"""Construye el Contexto de limpieza a partir de los catálogos publicados."""

from __future__ import annotations

import datetime as dt
from collections import Counter

from app.limpieza.base import Contexto
from app.limpieza.texto import clave
from ml.catalogos import Catalogos

MARGEN_FECHAS = dt.timedelta(days=366)


def contexto_desde_catalogos(cat: Catalogos) -> Contexto:
    t = cat.tiendas
    # Nombres para reconocer una tienda por texto: nombre completo y nombre sin la marca.
    candidatos: list[tuple[str, int]] = []
    for tid, nombre in zip(t.tienda_id.astype(int), t.nombre):
        candidatos.append((clave(nombre), tid))
        candidatos.append((clave(nombre.replace("NovaMercado", "")), tid))
    repetidos = Counter(k for k, _ in set(candidatos))
    nombres = {k: tid for k, tid in candidatos if k and repetidos[k] == 1}

    fer = cat.feriados.fecha
    return Contexto(
        apertura={int(i): f.date() for i, f in zip(t.tienda_id, t.fecha_apertura)},
        nombres_tienda=nombres,
        familias=dict(zip(cat.familias.familia_id, cat.familias.nombre)),
        calendario_hasta=fer.max().date(),
        fecha_min=(fer.min() - MARGEN_FECHAS).date(),
        fecha_max=(fer.max() + MARGEN_FECHAS).date(),
    )
