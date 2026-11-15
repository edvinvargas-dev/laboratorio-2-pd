"""Políticas de limpieza para las solicitudes de predicción y de observación.

Principio (ver DECISIONES.md):
  - reparar   : la interpretación es única y no cambia el significado.
  - advertir  : se respondió suponiendo algo; la respuesta dice qué.
  - rechazar  : no se sabe qué tienda o qué fecha, o responder obligaría a inventar.
"""

from __future__ import annotations

from typing import Any

from app.limpieza.base import Bitacora, Contexto, Rechazo
from app.limpieza.campos import resolver_campos
from app.limpieza.valores import a_familia, a_fecha, a_id_tienda, a_numero
from app.schemas import ObservacionCalidad, SolicitudObservacion, SolicitudPrediccion

# ------------------------------------------------------------ estructura general


def _desenvolver(raw: Any, esperados: set[str], bit: Bitacora) -> dict:
    """Acepta el objeto directo, una lista con un solo objeto o un objeto envuelto en otro."""
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict):
        bit.reparar("$", "el cuerpo era una lista con un solo objeto; se usó ese objeto")
        raw = raw[0]
    if not isinstance(raw, dict):
        raise Rechazo("El cuerpo debe ser un objeto JSON con los campos del contrato")
    if len(raw) == 1:
        (k, v), = raw.items()
        if isinstance(v, dict) and len(v) >= 2 and k not in esperados:
            bit.reparar("$", f"el objeto venía envuelto en {k!r}; se usó su contenido")
            return v
    return raw


def _tienda(d: dict, ctx: Contexto, bit: Bitacora) -> int:
    if d.get("tienda_id") is None:
        raise Rechazo("Falta tienda_id: no se puede saber de qué tienda es la solicitud")
    try:
        t, nota = a_id_tienda(d["tienda_id"], ctx.nombres_tienda)
    except ValueError as e:
        raise Rechazo(f"tienda_id inválido: {e}") from None
    if t not in ctx.tiendas:
        raise Rechazo(f"tienda_id {t} no existe en el catálogo de tiendas")
    if nota:
        bit.reparar("tienda_id", nota)
    return t


def _fecha(d: dict, tienda: int, ctx: Contexto, bit: Bitacora):
    if d.get("fecha") is None:
        raise Rechazo("Falta fecha: no se puede saber qué día se solicita")
    try:
        fi = a_fecha(d["fecha"])
    except ValueError as e:
        raise Rechazo(f"fecha inválida: {e}") from None
    f = fi.fecha
    if not ctx.fecha_min <= f <= ctx.fecha_max:
        raise Rechazo(f"fecha {f.isoformat()} fuera del rango operativo "
                      f"({ctx.fecha_min.isoformat()} a {ctx.fecha_max.isoformat()})")
    if f < ctx.apertura[tienda]:
        raise Rechazo(f"la tienda {tienda} abrió el {ctx.apertura[tienda].isoformat()}; "
                      f"no hay ventas el {f.isoformat()}")
    if fi.nota:
        bit.reparar("fecha", fi.nota)
    if fi.supuesto:
        bit.advertir("fecha", fi.supuesto)
    return f


def _items(d: dict, clave_lista: str, clave_valor: str, ctx: Contexto, bit: Bitacora) -> list[tuple[int, Any]]:
    """Normaliza la lista de familias a [(índice_original, item)]. Acepta también {familia: valor}."""
    v = d.get(clave_lista)
    if isinstance(v, dict) and v:
        bit.reparar(clave_lista, "venía como objeto {familia: valor}; se convirtió a lista")
        v = [{"familia_id": k, clave_valor: x} for k, x in v.items()]
    if not isinstance(v, list) or not v:
        raise Rechazo(f"{clave_lista} debe ser una lista no vacía")
    return list(enumerate(v))


def _familia_de(item: Any, ruta: str, ctx: Contexto, bit: Bitacora, clave_valor: str):
    """(familia_id | None, campos_del_item). None → el item se omite (ya se advirtió)."""
    if isinstance(item, str):  # solo el nombre de la familia
        item = {"familia_id": item}
    if not isinstance(item, dict):
        bit.advertir(ruta, f"elemento {item!r} no es un objeto; se omitió")
        return None, {}
    campos = resolver_campos(item, ["familia_id", clave_valor], f"{ruta}.", bit)
    try:
        fi = a_familia(campos.get("familia_id"), ctx.familias)
    except ValueError as e:
        bit.advertir(f"{ruta}.familia_id", f"{e}; se omitió")
        return None, campos
    if fi.nota:
        bit.reparar(f"{ruta}.familia_id", fi.nota)
    if fi.supuesto:
        bit.advertir(f"{ruta}.familia_id", fi.supuesto)
    return fi.familia_id, campos


def _deduplicar(valores: dict[str, list[tuple[str, Any]]], bit: Bitacora) -> dict[str, Any]:
    """Familia repetida: mismo valor → reparar; distinto → advertir y usar el último."""
    final = {}
    for fam, lista in valores.items():
        rutas = [r for r, _ in lista]
        distintos = {repr(x) for _, x in lista}
        if len(lista) > 1:
            if len(distintos) == 1:
                bit.reparar(rutas[-1] + ".familia_id", f"familia {fam!r} repetida con el mismo valor; se usó una vez")
            else:
                bit.advertir(rutas[-1] + ".familia_id",
                             f"familia {fam!r} repetida con valores distintos {[x for _, x in lista]}; "
                             f"se usó el último ({lista[-1][1]})")
        final[fam] = lista[-1][1]
    return final


# ---------------------------------------------------------------- predicción


def _promocion(campos: dict, ruta: str, bit: Bitacora) -> int:
    lugar = f"{ruta}.en_promocion"
    if campos.get("en_promocion") is None:
        bit.advertir(lugar, "sin dato de promoción; se supuso 0")
        return 0
    v = campos["en_promocion"]
    try:
        x, reparado = a_numero(v)
    except ValueError:
        bit.advertir(lugar, f"{v!r} no es una cantidad; se supuso 0")
        return 0
    if x < 0:
        bit.advertir(lugar, f"{v!r} es negativo; se supuso 0")
        return 0
    if not float(x).is_integer():
        bit.advertir(lugar, f"{v!r} no es entero; se redondeó a {round(x)}")
        return int(round(x))
    if reparado:
        bit.reparar(lugar, f"{v!r} se interpretó como {int(x)}")
    return int(x)


def limpiar_prediccion(raw: Any, ctx: Contexto) -> tuple[SolicitudPrediccion, list[ObservacionCalidad]]:
    bit = Bitacora()
    d = resolver_campos(_desenvolver(raw, {"tienda_id", "fecha", "familias"}, bit),
                        ["tienda_id", "fecha", "familias"], "", bit)
    tienda = _tienda(d, ctx, bit)
    fecha = _fecha(d, tienda, ctx, bit)
    if fecha > ctx.calendario_hasta:
        bit.advertir("fecha", f"posterior al calendario de feriados ({ctx.calendario_hasta.isoformat()}); "
                              "se supuso un día sin feriados")

    por_familia: dict[str, list[tuple[str, int]]] = {}
    for i, item in _items(d, "familias", "en_promocion", ctx, bit):
        ruta = f"familias[{i}]"
        fam, campos = _familia_de(item, ruta, ctx, bit, "en_promocion")
        if fam is not None:
            por_familia.setdefault(fam, []).append((ruta, _promocion(campos, ruta, bit)))
    promos = _deduplicar(por_familia, bit)
    if not promos:
        raise Rechazo("Ninguna familia de la solicitud es válida")

    faltan = [f for f in sorted(ctx.familias) if f not in promos]
    if faltan:
        bit.advertir("familias", f"faltan familias que la tienda vende: {faltan}; se agregaron con en_promocion=0")
        promos.update({f: 0 for f in faltan})

    sol = SolicitudPrediccion(
        tienda_id=tienda, fecha=fecha,
        familias=[{"familia_id": f, "en_promocion": p} for f, p in promos.items()],
    )
    return sol, bit.observaciones


# ------------------------------------------------------------- observaciones


def _ventas(campos: dict, ruta: str, bit: Bitacora) -> int | None:
    """None → no se guarda (no se inventan ventas)."""
    lugar = f"{ruta}.ventas"
    v = campos.get("ventas")
    if v is None:
        bit.advertir(lugar, "sin dato de ventas; no se guardó este registro")
        return None
    try:
        x, reparado = a_numero(v)
    except ValueError:
        bit.advertir(lugar, f"{v!r} no es una cantidad; no se guardó este registro")
        return None
    if x < 0:
        bit.advertir(lugar, f"{v!r} es negativo (¿devoluciones?); no se guardó este registro")
        return None
    if not float(x).is_integer():
        bit.advertir(lugar, f"{v!r} no es entero; se redondeó a {round(x)}")
        return int(round(x))
    if reparado:
        bit.reparar(lugar, f"{v!r} se interpretó como {int(x)}")
    return int(x)


def limpiar_observacion(raw: Any, ctx: Contexto) -> tuple[SolicitudObservacion, list[ObservacionCalidad]]:
    bit = Bitacora()
    d = resolver_campos(_desenvolver(raw, {"tienda_id", "fecha", "ventas"}, bit),
                        ["tienda_id", "fecha", "ventas"], "", bit)
    tienda = _tienda(d, ctx, bit)
    fecha = _fecha(d, tienda, ctx, bit)

    por_familia: dict[str, list[tuple[str, int]]] = {}
    for i, item in _items(d, "ventas", "ventas", ctx, bit):
        ruta = f"ventas[{i}]"
        fam, campos = _familia_de(item, ruta, ctx, bit, "ventas")
        if fam is None:
            continue
        v = _ventas(campos, ruta, bit)
        if v is not None:
            por_familia.setdefault(fam, []).append((ruta, v))
    ventas = _deduplicar(por_familia, bit)
    if not ventas:
        raise Rechazo("Ningún registro de ventas es válido")

    sol = SolicitudObservacion(
        tienda_id=tienda, fecha=fecha,
        ventas=[{"familia_id": f, "ventas": v} for f, v in ventas.items()],
    )
    return sol, bit.observaciones
