"""Orquestador sobre la API REST de Airflow 3 (v2).

- disparar(): crea un dag_run con un id propio (`rt_<uuid>`), que es el `id` del contrato.
- estado(id): traduce el estado de Airflow al del contrato:
      queued / running        → en_curso
      success                 → exitoso + promovido/version/motivo (XCom de la tarea `reentrenar`)
      failed                  → fallido + version vigente + qué tarea falló
  Un id que Airflow no conoce → None (404 en la API).
- Autenticación: token JWT de /auth/token (SimpleAuthManager); se renueva si expira.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Callable

import httpx

from app.servicios.orquestador import NoDisponible

log = logging.getLogger("orquestador")

EN_CURSO = {"queued", "running", "restarting", "up_for_retry", "scheduled", "deferred"}


class OrquestadorAirflow:
    def __init__(self, url: str, usuario: str, clave: str, version_vigente: Callable[[], str | None],
                 dag_id: str = "reentrenamiento", tarea_resultado: str = "reentrenar",
                 transporte: httpx.BaseTransport | None = None, timeout: float = 10.0):
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout, transport=transporte)
        self.usuario, self.clave = usuario, clave
        self.version_vigente = version_vigente
        self.dag_id, self.tarea_resultado = dag_id, tarea_resultado
        self._token: str | None = None

    # ---------------------------------------------------------------- http

    def _autenticar(self) -> None:
        r = self.http.post("/auth/token", json={"username": self.usuario, "password": self.clave})
        r.raise_for_status()
        self._token = r.json()["access_token"]

    def _pedir(self, metodo: str, ruta: str, **kw) -> httpx.Response:
        if self._token is None:
            self._autenticar()
        r = self.http.request(metodo, ruta, headers={"Authorization": f"Bearer {self._token}"}, **kw)
        if r.status_code == 401:  # token vencido
            self._autenticar()
            r = self.http.request(metodo, ruta, headers={"Authorization": f"Bearer {self._token}"}, **kw)
        return r

    # ------------------------------------------------------------ interfaz

    def ping(self) -> bool:
        try:
            r = self.http.get("/api/v2/monitor/health", timeout=3)
            d = r.json()
            return r.status_code == 200 and all(
                d.get(c, {}).get("status") == "healthy" for c in ("metadatabase", "scheduler"))
        except Exception:
            return False

    def disparar(self) -> str:
        id_ejecucion = f"rt_{uuid.uuid4().hex}"
        try:
            r = self._pedir("POST", f"/api/v2/dags/{self.dag_id}/dagRuns",
                            json={"dag_run_id": id_ejecucion, "logical_date": None})
        except httpx.HTTPError as e:
            raise NoDisponible(f"Airflow no responde ({e.__class__.__name__})") from None
        if r.status_code not in (200, 201):
            raise NoDisponible(f"Airflow rechazó el disparo ({r.status_code}): {r.text[:200]}")
        log.info("reentrenamiento disparado: %s", id_ejecucion)
        return id_ejecucion

    def estado(self, id_ejecucion: str) -> dict | None:
        try:
            r = self._pedir("GET", f"/api/v2/dags/{self.dag_id}/dagRuns/{id_ejecucion}")
        except httpx.HTTPError as e:
            raise NoDisponible(f"Airflow no responde ({e.__class__.__name__})") from None
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise NoDisponible(f"Airflow respondió {r.status_code}")
        estado = r.json().get("state")
        if estado in EN_CURSO or estado is None:
            return {"estado": "en_curso"}
        if estado == "success":
            resultado = self._resultado(id_ejecucion)
            if resultado:
                return {"estado": "exitoso", "promovido": bool(resultado.get("promovido")),
                        "version": str(resultado.get("version") or self._vigente()),
                        "motivo": str(resultado.get("motivo", "")),
                        "version_candidata": resultado.get("version_candidata")}
            return {"estado": "exitoso", "promovido": False, "version": self._vigente(),
                    "motivo": "La ejecución terminó sin reportar resultado"}
        return {"estado": "fallido", "promovido": False, "version": self._vigente(),
                "motivo": self._motivo_fallo(id_ejecucion)}

    # ------------------------------------------------------------ detalle

    def _vigente(self) -> str:
        return str(self.version_vigente() or "")

    def _resultado(self, id_ejecucion: str) -> dict | None:
        r = self._pedir("GET", f"/api/v2/dags/{self.dag_id}/dagRuns/{id_ejecucion}/taskInstances/"
                               f"{self.tarea_resultado}/xcomEntries/return_value")
        if r.status_code != 200:
            return None
        valor = r.json().get("value")
        if isinstance(valor, str):
            try:
                valor = json.loads(valor)
            except json.JSONDecodeError:
                return None
        return valor if isinstance(valor, dict) else None

    def _motivo_fallo(self, id_ejecucion: str) -> str:
        r = self._pedir("GET", f"/api/v2/dags/{self.dag_id}/dagRuns/{id_ejecucion}/taskInstances")
        try:
            fallidas = [t["task_id"] for t in r.json().get("task_instances", []) if t.get("state") == "failed"]
        except Exception:
            fallidas = []
        tareas = ", ".join(fallidas) or "desconocida"
        return f"Falló la tarea {tareas}; el modelo vigente no cambió"
