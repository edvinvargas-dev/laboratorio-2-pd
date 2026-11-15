"""Servicio FastAPI de NovaMercado. Endpoints delgados: leer, limpiar, delegar, responder.

Ejecutar en local (desde la raíz del repo):
    .venv\\Scripts\\python -m uvicorn app.main:app --app-dir api --port 8000
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.dependencias import Dependencias, construir_dependencias
from app.limpieza import Rechazo, limpiar_observacion, limpiar_prediccion
from app.schemas import (
    Calidad,
    RespuestaHealth,
    RespuestaModelo,
    RespuestaObservacion,
    RespuestaPrediccion,
    RespuestaReentrenarEstado,
    RespuestaReentrenarInicio,
)
from app.servicios.orquestador import NoDisponible
from app.servicios.prediccion import predecir


def create_app(deps: Dependencias | None = None) -> FastAPI:
    app = FastAPI(title="NovaMercado — Pronóstico diario de ventas", version="1.0.0")
    app.state.deps = deps

    def d() -> Dependencias:
        if app.state.deps is None:  # carga perezosa: las pruebas inyectan las suyas
            app.state.deps = construir_dependencias()
        return app.state.deps

    def rechazar(endpoint: str, crudo: Any, detalle: str) -> JSONResponse:
        try:
            d().repo.registrar_rechazo(endpoint, crudo, detalle)
        except Exception:  # registrar es secundario: el rechazo se responde igual
            pass
        return JSONResponse(status_code=422, content={"detail": detalle})

    async def cuerpo(request: Request) -> Any:
        raw = await request.body()
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise Rechazo("El cuerpo no es JSON válido") from None

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "; ".join(e["msg"] for e in exc.errors())})

    # ------------------------------------------------------------ predicción

    @app.post("/v1/prediccion", response_model=RespuestaPrediccion)
    async def prediccion(request: Request):
        crudo = None
        try:
            crudo = await cuerpo(request)
            sol, obs = limpiar_prediccion(crudo, d().contexto)
        except Rechazo as e:
            return rechazar("/v1/prediccion", crudo, e.detalle)
        modelo = d().gestor.actual()
        if modelo is None:
            raise HTTPException(503, "No hay un modelo cargado")
        predicciones, obs_historia = predecir(sol, modelo, d().repo, d().cat)
        resp = RespuestaPrediccion(
            tienda_id=sol.tienda_id, fecha=sol.fecha, version_modelo=modelo.version,
            predicciones=predicciones, calidad=Calidad.desde(obs + obs_historia),
        )
        d().repo.registrar_prediccion(crudo, sol, resp)
        return resp

    # ---------------------------------------------------------- observaciones

    @app.post("/v1/observaciones", response_model=RespuestaObservacion)
    async def observaciones(request: Request):
        crudo = None
        try:
            crudo = await cuerpo(request)
            sol, obs = limpiar_observacion(crudo, d().contexto)
        except Rechazo as e:
            return rechazar("/v1/observaciones", crudo, e.detalle)
        calidad = Calidad.desde(obs)
        n = d().repo.guardar_observacion(crudo, sol, calidad)
        return RespuestaObservacion(registros_guardados=n, calidad=calidad)

    # ---------------------------------------------------------- administración

    @app.post("/admin/reentrenar", status_code=202, response_model=RespuestaReentrenarInicio)
    def reentrenar():
        try:
            return RespuestaReentrenarInicio(id=d().orquestador.disparar())
        except NoDisponible as e:
            raise HTTPException(503, f"No se puede iniciar el reentrenamiento: {e}") from None

    @app.get("/admin/reentrenar/{id_ejecucion}", response_model=RespuestaReentrenarEstado,
             response_model_exclude_none=True)
    def estado_reentrenamiento(id_ejecucion: str):
        est = d().orquestador.estado(id_ejecucion)
        if est is None:
            raise HTTPException(404, f"Ejecución {id_ejecucion!r} desconocida")
        return est

    @app.get("/modelo", response_model=RespuestaModelo)
    def modelo():
        m = d().gestor.actual()
        if m is None:
            raise HTTPException(503, "No hay un modelo cargado")
        return RespuestaModelo(nombre=m.nombre, alias=m.alias, version=m.version)

    @app.get("/health", response_model=RespuestaHealth, response_model_exclude_none=True)
    def health():
        deps = d()
        modelo = deps.gestor.actual()
        if modelo is None:
            return JSONResponse(status_code=503, content={"estado": "degradado", "motivo": "No hay un modelo cargado"})
        caidas = [nombre for nombre, ok in [
            ("base de datos", deps.repo.ping()),
            ("MLflow", deps.gestor.mlflow_disponible()),
            ("Airflow", deps.orquestador.ping()),
        ] if not ok]
        if caidas:
            return RespuestaHealth(estado="degradado", motivo="No disponible: " + ", ".join(caidas),
                                   version_modelo=modelo.version)
        return RespuestaHealth(estado="ok", version_modelo=modelo.version)

    return app


app = create_app()
