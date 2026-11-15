"""Normalización de texto: base de todas las comparaciones tolerantes."""

from __future__ import annotations

import difflib
import re
import unicodedata

PALABRAS_VACIAS = {"y", "e", "de", "del", "la", "las", "el", "los", "para", "and", "of", "the"}


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def tokens(s: str) -> list[str]:
    """'Frutas y Verduras' → ['frutas', 'verduras'];  'tiendaId' → ['tienda', 'id']."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(s))  # camelCase → camel Case
    s = sin_acentos(s).lower()
    return [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in PALABRAS_VACIAS]


def clave(s: str) -> str:
    return "_".join(tokens(s))


def singular(t: str) -> str:
    """Raíz muy simple para tolerar singular/plural en español ('lacteo' ≈ 'lacteos')."""
    for suf in ("es", "s"):
        if len(t) > 4 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def clave_raiz(s: str) -> str:
    return "_".join(singular(t) for t in tokens(s))


def parecido_unico(objetivo: str, opciones: list[str], umbral: float = 0.8) -> str | None:
    """La opción más parecida si supera el umbral y no hay empate cercano (evita adivinar)."""
    puntajes = sorted(((difflib.SequenceMatcher(None, objetivo, o).ratio(), o) for o in opciones), reverse=True)
    if not puntajes or puntajes[0][0] < umbral:
        return None
    if len(puntajes) > 1 and puntajes[0][0] - puntajes[1][0] < 0.05:
        return None
    return puntajes[0][1]
