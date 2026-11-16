"""Pruebas de la defensa del contrato: políticas reparar / advertir / rechazar.

Incluye los 10 casos del catálogo (E01–E10) y casos que NO están en él, para
comprobar que las reglas son generales.
"""

import copy
import datetime as dt

import pytest

from app.limpieza import Rechazo, limpiar_observacion, limpiar_prediccion
from app.limpieza.contexto import contexto_desde_catalogos
from app.limpieza.valores import a_fecha, a_numero
from app.schemas import Calidad
from tests.conftest import FAMILIAS, FECHA


@pytest.fixture
def ctx(cat):
    return contexto_desde_catalogos(cat)


@pytest.fixture
def pred():
    return {"tienda_id": 5, "fecha": FECHA,
            "familias": [{"familia_id": f, "en_promocion": 0} for f in FAMILIAS]}


@pytest.fixture
def obs():
    return {"tienda_id": 5, "fecha": FECHA, "ventas": [{"familia_id": f, "ventas": 100} for f in FAMILIAS]}


def acciones(observaciones):
    return [(o.campo, o.accion) for o in observaciones]


def estado(observaciones):
    return Calidad.desde(observaciones).estado


# ============================================================ catálogo E01–E10

@pytest.mark.parametrize("valor", ["T05", "5", "05", 5.0, "tienda 5", "NovaMercado Quetzaltenango", "Quetzaltenango"])
def test_E01_tienda_texto_o_prefijo_se_repara(ctx, pred, valor):
    pred["tienda_id"] = valor
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.tienda_id == 5 and acciones(o) == [("tienda_id", "reparar")]


def test_E01_nombre_con_numero_no_se_confunde(ctx, pred):
    pred["tienda_id"] = "NovaMercado Zona 10"  # es la tienda 1, no la 10
    assert limpiar_prediccion(pred, ctx)[0].tienda_id == 1


@pytest.mark.parametrize("valor", ["LÁCTEOS", "lacteos ", "Lácteos", "lacteo", "LACTEOS"])
def test_E02_familia_escrita_distinto_se_repara(ctx, pred, valor):
    pred["familias"][6]["familia_id"] = valor
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.familias[6].familia_id == "lacteos"
    assert acciones(o) == [("familias[6].familia_id", "reparar")]


def test_E02_familia_por_nombre_con_palabras(ctx, pred):
    pred["familias"][5]["familia_id"] = "Frutas y Verduras"
    pred["familias"][11]["familia_id"] = "Snacks y dulces"
    sol, o = limpiar_prediccion(pred, ctx)
    assert [f.familia_id for f in sol.familias] == FAMILIAS and estado(o) == "corregido"


@pytest.mark.parametrize("valor, esperado", [("3", 3), (2.0, 2), (" 9 ", 9), ("9.0", 9)])
def test_E03_promocion_texto_o_decimal_se_repara(ctx, pred, valor, esperado):
    pred["familias"][2]["en_promocion"] = valor
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.familias[2].en_promocion == esperado and estado(o) == "corregido"


@pytest.mark.parametrize("valor", ["2025-11-17T00:00:00", "17/11/2025", "2025/11/17", "17-11-2025",
                                   "20251117", "17 nov 2025", "17 de noviembre de 2025", "11/17/2025"])
def test_E04_fecha_en_otro_formato_se_repara(ctx, pred, valor):
    pred["fecha"] = valor
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.fecha == dt.date(2025, 11, 17) and acciones(o) == [("fecha", "reparar")]


def test_E05_faltan_familias_se_agregan_con_advertencia(ctx, pred):
    pred["familias"] = [f for f in pred["familias"] if f["familia_id"] not in ("bebe", "mascotas")]
    sol, o = limpiar_prediccion(pred, ctx)
    assert {f.familia_id for f in sol.familias} == set(FAMILIAS)
    assert estado(o) == "advertencia" and "bebe" in o[0].detalle and "mascotas" in o[0].detalle


def test_E06_familia_repetida_con_valores_distintos_usa_la_ultima(ctx, pred):
    pred["familias"].append({"familia_id": "abarrotes", "en_promocion": 3})
    sol, o = limpiar_prediccion(pred, ctx)
    assert len(sol.familias) == 12
    assert next(f for f in sol.familias if f.familia_id == "abarrotes").en_promocion == 3
    assert estado(o) == "advertencia"


def test_E06_familia_repetida_igual_solo_se_repara(ctx, pred):
    pred["familias"].append({"familia_id": "abarrotes", "en_promocion": 0})
    _, o = limpiar_prediccion(pred, ctx)
    assert estado(o) == "corregido"


@pytest.mark.parametrize("nombre", ["tienda", "tiendaId", "TiendaID", "id_tienda", "store_id", "Tienda Id"])
def test_E07_campo_renombrado_se_repara(ctx, pred, nombre):
    pred[nombre] = pred.pop("tienda_id")
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.tienda_id == 5 and acciones(o) == [(nombre, "reparar")]


def test_E08_ventas_negativas_no_se_guardan(ctx, obs):
    obs["ventas"][5]["ventas"] = -4
    sol, o = limpiar_observacion(obs, ctx)
    assert "frutas_verduras" not in {v.familia_id for v in sol.ventas} and len(sol.ventas) == 11
    assert acciones(o) == [("ventas[5].ventas", "advertir")]


def test_E09_envio_repetido_es_valido(ctx, obs):
    a, oa = limpiar_observacion(obs, ctx)
    b, ob = limpiar_observacion(copy.deepcopy(obs), ctx)
    assert a == b and oa == ob == []  # la idempotencia la garantiza el repositorio


@pytest.mark.parametrize("valor, esperado", [("1,234", 1234), ("812,0", 812), ("1.234", 1234),
                                             ("1.234,0", 1234), ("1 234", 1234), (50.0, 50)])
def test_E10_numero_con_formato_se_repara(ctx, obs, valor, esperado):
    obs["ventas"][1]["ventas"] = valor
    sol, o = limpiar_observacion(obs, ctx)
    assert sol.ventas[1].ventas == esperado and acciones(o) == [("ventas[1].ventas", "reparar")]


# =================================================== casos fuera del catálogo

def test_familia_con_error_de_tipeo_se_advierte(ctx, pred):
    pred["familias"][0]["familia_id"] = "abarotes"
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.familias[0].familia_id == "abarrotes" and estado(o) == "advertencia"


def test_familia_inexistente_se_omite_y_se_completa(ctx, pred):
    pred["familias"][0]["familia_id"] = "ropa"
    sol, o = limpiar_prediccion(pred, ctx)
    assert "ropa" not in str(sol) and len(sol.familias) == 12  # abarrotes se agrega como faltante
    assert estado(o) == "advertencia"


def test_fecha_ambigua_se_advierte(ctx, pred):
    pred["fecha"] = "05/11/2025"
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.fecha == dt.date(2025, 11, 5) and acciones(o) == [("fecha", "advertir")]


@pytest.mark.parametrize("valor", ["2025-02-30", "mañana", 20251117, None, "1800-01-01"])
def test_fecha_imposible_se_rechaza(ctx, pred, valor):
    pred["fecha"] = valor
    with pytest.raises(Rechazo):
        limpiar_prediccion(pred, ctx)


def test_fecha_imposible_explica_en_espanol(ctx, pred):
    pred["fecha"] = "2026-02-30"
    with pytest.raises(Rechazo, match="no es una fecha válida del calendario"):
        limpiar_prediccion(pred, ctx)


def test_fecha_posterior_al_calendario_se_advierte(ctx, pred):
    pred["fecha"] = "2027-03-01"
    _, o = limpiar_prediccion(pred, ctx)
    assert acciones(o) == [("fecha", "advertir")]


@pytest.mark.parametrize("valor", [99, "T5-2", True, 5.5, "abc", None])
def test_tienda_no_identificable_se_rechaza(ctx, pred, valor):
    pred["tienda_id"] = valor
    with pytest.raises(Rechazo):
        limpiar_prediccion(pred, ctx)


def test_campos_conflictivos_se_rechazan(ctx, pred):
    pred["tienda"] = 1  # tienda_id = 5 y tienda = 1: no se sabe cuál es
    with pytest.raises(Rechazo, match="distintos"):
        limpiar_prediccion(pred, ctx)


def test_campo_extra_se_ignora_con_advertencia(ctx, pred):
    pred["canal"] = "web"
    _, o = limpiar_prediccion(pred, ctx)
    assert acciones(o) == [("canal", "advertir")]


def test_campo_con_error_de_tipeo_se_advierte(ctx, pred):
    pred["fehca"] = pred.pop("fecha")
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.fecha == dt.date(2025, 11, 17) and acciones(o) == [("fehca", "advertir")]


@pytest.mark.parametrize("valor, accion", [(None, "advertir"), ("muchas", "advertir"), (-2, "advertir"),
                                           (2.5, "advertir")])
def test_promocion_invalida_se_advierte(ctx, pred, valor, accion):
    pred["familias"][0]["en_promocion"] = valor
    _, o = limpiar_prediccion(pred, ctx)
    assert acciones(o) == [("familias[0].en_promocion", accion)]


def test_promocion_ausente_se_supone_cero(ctx, pred):
    del pred["familias"][0]["en_promocion"]
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.familias[0].en_promocion == 0 and estado(o) == "advertencia"


def test_familias_como_objeto(ctx, pred):
    pred["familias"] = {f: 1 for f in FAMILIAS}
    sol, o = limpiar_prediccion(pred, ctx)
    assert len(sol.familias) == 12 and all(f.en_promocion == 1 for f in sol.familias)
    assert estado(o) == "corregido"


def test_cuerpo_envuelto_o_en_lista(ctx, pred):
    for envuelto in ({"solicitud": pred}, [pred]):
        sol, o = limpiar_prediccion(copy.deepcopy(envuelto), ctx)
        assert sol.tienda_id == 5 and acciones(o) == [("$", "reparar")]


def test_varios_problemas_a_la_vez(ctx, pred):
    pred = {"Tienda": "T05", "date": "17/11/2025",
            "items": [{"familia": "LÁCTEOS", "promo": "2"}, {"familia_id": "Carnes", "en_promocion": 1.0}]}
    sol, o = limpiar_prediccion(pred, ctx)
    assert sol.tienda_id == 5 and sol.fecha == dt.date(2025, 11, 17)
    assert sol.familias[0].familia_id == "lacteos" and sol.familias[0].en_promocion == 2
    assert estado(o) == "advertencia"  # por las 10 familias faltantes


def test_observacion_sin_registros_validos_se_rechaza(ctx, obs):
    obs["ventas"] = [{"familia_id": "abarrotes", "ventas": -1}]
    with pytest.raises(Rechazo):
        limpiar_observacion(obs, ctx)


@pytest.mark.parametrize("valor", [None, "n/d", "1,2,3,4"])
def test_ventas_ilegibles_no_se_guardan(ctx, obs, valor):
    obs["ventas"][0]["ventas"] = valor
    sol, o = limpiar_observacion(obs, ctx)
    assert len(sol.ventas) == 11 and estado(o) == "advertencia"


def test_ventas_decimales_se_redondean_con_advertencia(ctx, obs):
    obs["ventas"][0]["ventas"] = "12,5"
    sol, o = limpiar_observacion(obs, ctx)
    assert sol.ventas[0].ventas == 12 and estado(o) == "advertencia"


# ======================================================== funciones de valores

@pytest.mark.parametrize("texto, esperado", [("1,234,567", 1234567), ("1.234.567,89", 1234567.89),
                                             ("0,5", 0.5), ("-3", -3), ("+7", 7)])
def test_a_numero(texto, esperado):
    assert a_numero(texto)[0] == pytest.approx(esperado)


def test_a_fecha_iso_no_se_reporta():
    f = a_fecha("2025-11-17")
    assert f.fecha == dt.date(2025, 11, 17) and f.nota is None and f.supuesto is None
