"""Resolución de nombres de campo: 'tienda', 'tiendaId', 'id_tienda', 'store_id' → 'tienda_id'."""

from __future__ import annotations

from typing import Any

from app.limpieza.base import Bitacora, Rechazo
from app.limpieza.texto import clave, parecido_unico

SINONIMOS: dict[str, list[str]] = {
    "tienda_id": ["tienda", "id_tienda", "store", "store_id", "sucursal", "sucursal_id", "codigo_tienda", "tienda_codigo"],
    "fecha": ["date", "dia", "fecha_venta", "fecha_prediccion", "fecha_pronostico", "day"],
    "familias": ["familia", "productos", "items", "lineas", "detalle", "families", "familias_producto"],
    "familia_id": ["familia", "id_familia", "family", "family_id", "categoria", "categoria_id", "producto"],
    "en_promocion": ["promocion", "promociones", "promo", "promos", "en_promo", "productos_promocion",
                     "productos_en_promocion", "promotion", "on_promotion", "onpromotion"],
    "ventas": ["venta", "ventas_reales", "unidades", "cantidad", "sales", "total", "unidades_vendidas", "observaciones"],
}


def _canonico(k: str, esperados: list[str]) -> tuple[str | None, bool]:
    """(campo canónico, es_aproximado)."""
    if k in esperados:
        return k, False
    ck = clave(k)
    for canon in esperados:
        variantes = {clave(canon), *(clave(s) for s in SINONIMOS.get(canon, []))}
        if ck in variantes or sorted(ck.split("_")) == sorted(clave(canon).split("_")):
            return canon, False
    todas = {clave(s): canon for canon in esperados for s in [canon, *SINONIMOS.get(canon, [])]}
    parecido = parecido_unico(ck, list(todas), umbral=0.8)
    return (todas[parecido], True) if parecido else (None, False)


def resolver_campos(d: dict, esperados: list[str], ruta: str, bit: Bitacora) -> dict[str, Any]:
    """Devuelve {campo_canónico: valor}. Ignora (con advertencia) campos desconocidos."""
    salida: dict[str, Any] = {}
    origen: dict[str, str] = {}
    for k, v in d.items():
        canon, aproximado = _canonico(str(k), esperados)
        lugar = f"{ruta}{k}"
        if canon is None:
            bit.advertir(lugar, f"campo {k!r} no reconocido; se ignoró")
            continue
        if canon in salida:
            if salida[canon] != v:
                raise Rechazo(f"{ruta}{canon}: llegan valores distintos en {origen[canon]!r} y {k!r}")
            bit.reparar(lugar, f"campo {k!r} duplica a {origen[canon]!r} con el mismo valor; se ignoró")
            continue
        salida[canon], origen[canon] = v, k
        if aproximado:
            bit.advertir(lugar, f"campo {k!r} no existe; por parecido se supuso {canon!r}")
        elif k != canon:
            bit.reparar(lugar, f"campo {k!r} se interpretó como {canon!r}")
    return salida
