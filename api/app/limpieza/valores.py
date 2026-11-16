"""Interpretación de valores sueltos: números, identificadores, fechas y familias.

Cada función devuelve el valor interpretado y una descripción de lo que hizo
(None si el valor ya venía bien), o lanza ValueError si no hay interpretación posible.
Las decisiones de política (reparar/advertir/rechazar) se toman en `solicitudes.py`.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from typing import Any

from app.limpieza.texto import clave, clave_raiz, parecido_unico, sin_acentos

# ------------------------------------------------------------------- números


def a_numero(v: Any) -> tuple[float, bool]:
    """(valor, reparado). Acepta 8, 8.0, '8', ' 1,234 ', '812,0', '1.234,5', '1 234'."""
    if isinstance(v, bool) or v is None:
        raise ValueError(f"{v!r} no es un número")
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"{v!r} no es un número finito")
        return float(v), isinstance(v, float)
    if not isinstance(v, str):
        raise ValueError(f"{v!r} no es un número")
    s = v.strip().replace(" ", "").replace(" ", "").replace("'", "")
    if not re.fullmatch(r"[+-]?[\d.,]+", s) or not re.search(r"\d", s):
        raise ValueError(f"{v!r} no es un número")
    signo = -1.0 if s.startswith("-") else 1.0
    s = s.lstrip("+-")
    if "," in s and "." in s:  # el último separador es el decimal
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        mil = "." if dec == "," else ","
        s = s.replace(mil, "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        partes = s.split(sep)
        # grupos de exactamente 3 dígitos tras cada separador → separador de miles
        if len(partes) > 2 or (len(partes) == 2 and len(partes[1]) == 3 and partes[0] not in ("", "0")):
            if all(len(p) == 3 for p in partes[1:]):
                s = "".join(partes)
            else:
                raise ValueError(f"{v!r} tiene separadores incoherentes")
        else:
            s = s.replace(sep, ".")
    return signo * float(s), True


# ------------------------------------------------------------ identificadores


def a_id_tienda(v: Any, nombres: dict[str, int]) -> tuple[int, str | None]:
    """5 → 5;  '5'/'05'/'T05'/5.0 → 5;  'NovaMercado Mixco'/'Mixco' → 2 (si es único)."""
    if isinstance(v, bool) or v is None:
        raise ValueError("sin valor")
    if isinstance(v, int):
        return v, None
    if isinstance(v, float):
        if v.is_integer():
            return int(v), f"{v!r} se interpretó como {int(v)}"
        raise ValueError(f"{v!r} no es un identificador entero")
    if isinstance(v, str):
        if clave(v) in nombres:  # primero el nombre: 'NovaMercado Zona 10' es la tienda 1, no la 10
            t = nombres[clave(v)]
            return t, f"{v!r} se interpretó como la tienda {t}"
        grupos = re.findall(r"\d+", v)
        if len(grupos) == 1 and not re.search(r"\d[.,]\d", v):
            return int(grupos[0]), f"{v!r} se interpretó como {int(grupos[0])}"
    raise ValueError(f"{v!r} no identifica una tienda")


# --------------------------------------------------------------------- fechas

MESES = {
    "ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "ago": 8, "aug": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12,
}


@dataclass
class FechaInterpretada:
    fecha: dt.date
    nota: str | None = None  # qué se reparó
    supuesto: str | None = None  # qué se supuso (→ advertir)


def a_fecha(v: Any) -> FechaInterpretada:
    try:
        return _a_fecha(v)
    except ValueError as e:
        if str(e).startswith(repr(v)):  # mensaje propio, ya en español
            raise
        raise ValueError(f"{v!r} no es una fecha válida del calendario") from None  # p. ej. 30 de febrero


def _a_fecha(v: Any) -> FechaInterpretada:
    if not isinstance(v, str):
        raise ValueError(f"{v!r} no es una fecha en texto")
    s = v.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return FechaInterpretada(dt.date.fromisoformat(s))
    nota = f"{v!r} se interpretó como "

    # AAAA-MM-DD con otro separador y/o con hora: 2025/11/17, 2025-11-17T00:00:00
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T\s].*)?", s)
    if m:
        f = dt.date(int(m[1]), int(m[2]), int(m[3]))
        return FechaInterpretada(f, nota + f.isoformat())
    # AAAAMMDD
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        f = dt.date(int(m[1]), int(m[2]), int(m[3]))
        return FechaInterpretada(f, nota + f.isoformat())
    # DD/MM/AAAA o MM/DD/AAAA (con hora opcional)
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?:[T\s].*)?", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12 or a == b:  # solo puede ser día/mes
            f = dt.date(y, b, a)
            return FechaInterpretada(f, nota + f.isoformat())
        if b > 12:  # solo puede ser mes/día
            f = dt.date(y, a, b)
            return FechaInterpretada(f, nota + f.isoformat() + " (mes/día)")
        f = dt.date(y, b, a)  # ambigua: convención local día/mes
        return FechaInterpretada(f, supuesto=f"{v!r} es ambigua; se supuso día/mes: {f.isoformat()}")
    # 17 nov 2025, 17 de noviembre de 2025, nov 17 2025
    t = sin_acentos(s).lower()
    m = re.fullmatch(r"(\d{1,2})\s*(?:de\s+)?([a-z]+)\.?\s*(?:de\s+|,\s*)?(\d{4})", t) or None
    if m and m[2][:3] in MESES:
        f = dt.date(int(m[3]), MESES[m[2][:3]], int(m[1]))
        return FechaInterpretada(f, nota + f.isoformat())
    m = re.fullmatch(r"([a-z]+)\.?\s*(\d{1,2}),?\s*(\d{4})", t)
    if m and m[1][:3] in MESES:
        f = dt.date(int(m[3]), MESES[m[1][:3]], int(m[2]))
        return FechaInterpretada(f, nota + f.isoformat())
    raise ValueError(f"{v!r} no es una fecha reconocible")


# ------------------------------------------------------------------- familias


@dataclass
class FamiliaInterpretada:
    familia_id: str
    nota: str | None = None  # reparación inequívoca
    supuesto: str | None = None  # parecido aproximado (→ advertir)


def a_familia(v: Any, familias: dict[str, str]) -> FamiliaInterpretada:
    """`familias`: familia_id → nombre. Acepta id, nombre, mayúsculas, acentos, plural."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{v!r} no es una familia")
    if v in familias:
        return FamiliaInterpretada(v)
    for fn in (clave, clave_raiz):  # exacta tras normalizar; luego tolerando singular/plural
        mapa: dict[str, set[str]] = {}
        for fid, nombre in familias.items():
            for txt in (fid, nombre):
                mapa.setdefault(fn(txt), set()).add(fid)
        candidatos = mapa.get(fn(v), set())
        if len(candidatos) == 1:
            fid = candidatos.pop()
            return FamiliaInterpretada(fid, nota=f"{v!r} se interpretó como {fid!r}")
    opciones = {clave(t): fid for fid, nombre in familias.items() for t in (fid, nombre)}
    parecida = parecido_unico(clave(v), list(opciones))
    if parecida:
        fid = opciones[parecida]
        return FamiliaInterpretada(fid, supuesto=f"{v!r} no existe; por parecido se supuso {fid!r}")
    raise ValueError(f"familia {v!r} no existe")
