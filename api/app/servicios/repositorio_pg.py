"""Repositorio sobre PostgreSQL (base de datos propia del producto)."""

from __future__ import annotations

import datetime as dt
import functools
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from app.servicios.repositorio import RepositorioNoDisponible, _a_dataframe

ESQUEMA = Path(__file__).resolve().parents[3] / "db" / "esquema.sql"
CANDADO_INICIALIZACION = 726_001  # pg_advisory_lock: un solo proceso inicializa a la vez


def _protegido(fn):
    """Convierte errores de conexión en RepositorioNoDisponible (→ 503 en la API)."""

    @functools.wraps(fn)
    def envoltura(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (psycopg.OperationalError, PoolTimeout) as e:
            raise RepositorioNoDisponible(f"base de datos no disponible: {e.__class__.__name__}") from e

    return envoltura


class RepositorioPostgres:
    def __init__(self, url: str, esquema: str | Path | None = None, timeout: float = 5.0):
        self.esquema = Path(esquema) if esquema else ESQUEMA
        self.timeout = timeout
        # check: descarta conexiones muertas (p. ej. tras reiniciar la base) antes de usarlas
        self.pool = ConnectionPool(url, min_size=1, max_size=8, open=False, timeout=timeout,
                                   kwargs={"connect_timeout": 3}, check=ConnectionPool.check_connection)
        self.pool.open(wait=False)  # no bloquear el arranque si la base aún no está lista

    def cerrar(self) -> None:
        self.pool.close()

    # ----------------------------------------------------------------- arranque

    @_protegido
    def inicializar(self, data_dir: str | Path | None = None) -> bool:
        """Aplica el esquema y carga el histórico una sola vez. Devuelve True si lo cargó ahora."""
        with self.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(%s)", (CANDADO_INICIALIZACION,))
            c.execute(self.esquema.read_text(encoding="utf-8"))
            if c.execute("SELECT 1 FROM meta WHERE clave = 'historico_cargado'").fetchone():
                return False
            if data_dir is None:
                return False
            archivo = Path(data_dir) / "historico_ventas.csv"
            with c.cursor() as cur, cur.copy(
                "COPY historico_ventas (fecha, tienda_id, familia_id, ventas, en_promocion) "
                "FROM STDIN WITH (FORMAT csv, HEADER true)"
            ) as copia:
                copia.write(archivo.read_bytes())
            n = c.execute("SELECT count(*) FROM historico_ventas").fetchone()[0]
            c.execute("INSERT INTO meta (clave, valor) VALUES ('historico_cargado', %s)", (str(n),))
            return True

    def ping(self) -> bool:
        try:
            with self.pool.connection(timeout=2) as c:
                c.execute("SELECT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ lectura

    @_protegido
    def historia(self, tienda_id: int, desde: dt.date, hasta: dt.date) -> pd.DataFrame:
        with self.pool.connection() as c:
            filas = c.execute(
                "SELECT fecha, tienda_id, familia_id, ventas FROM ventas_conocidas "
                "WHERE tienda_id = %s AND fecha >= %s AND fecha < %s",
                (tienda_id, desde, hasta),
            ).fetchall()
        return _a_dataframe(filas)

    @_protegido
    def ventas_entrenamiento(self) -> pd.DataFrame:
        """Todas las ventas conocidas con su promoción (para el reentrenamiento)."""
        with self.pool.connection() as c:
            filas = c.execute(
                "SELECT fecha, tienda_id, familia_id, ventas, en_promocion, origen FROM ventas_entrenamiento"
            ).fetchall()
        df = pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion", "origen"])
        df["fecha"] = pd.to_datetime(df["fecha"])
        return df

    # ---------------------------------------------------------------- escritura

    @staticmethod
    def _solicitud(c, endpoint: str, crudo: Any, tienda_id, fecha, estado: str,
                   detalle: str | None = None, version: str | None = None) -> int:
        return c.execute(
            "INSERT INTO solicitudes (endpoint, cuerpo, tienda_id, fecha, estado, detalle_rechazo, version_modelo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (endpoint, None if crudo is None else Jsonb(crudo), tienda_id, fecha, estado, detalle, version),
        ).fetchone()[0]

    @staticmethod
    def _correcciones(c, solicitud_id: int, calidad) -> None:
        if calidad.observaciones:
            with c.cursor() as cur:
                cur.executemany(
                    "INSERT INTO correcciones (solicitud_id, campo, accion, detalle) VALUES (%s, %s, %s, %s)",
                    [(solicitud_id, o.campo, o.accion, o.detalle) for o in calidad.observaciones],
                )

    @_protegido
    def registrar_prediccion(self, crudo, solicitud, respuesta) -> None:
        promo = {f.familia_id: f.en_promocion for f in solicitud.familias}
        with self.pool.connection() as c, c.transaction():
            sid = self._solicitud(c, "/v1/prediccion", crudo, solicitud.tienda_id, solicitud.fecha,
                                  respuesta.calidad.estado, version=respuesta.version_modelo)
            self._correcciones(c, sid, respuesta.calidad)
            with c.cursor() as cur:
                cur.executemany(
                    "INSERT INTO predicciones (solicitud_id, tienda_id, fecha, familia_id, en_promocion, "
                    "venta_esperada, cantidad_sugerida, version_modelo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    [(sid, solicitud.tienda_id, solicitud.fecha, p.familia_id, promo[p.familia_id],
                      p.venta_esperada, p.cantidad_sugerida, respuesta.version_modelo)
                     for p in respuesta.predicciones],
                )

    @_protegido
    def registrar_rechazo(self, endpoint, crudo, detalle) -> None:
        with self.pool.connection() as c, c.transaction():
            self._solicitud(c, endpoint, crudo, None, None, "rechazado", detalle=detalle)

    @_protegido
    def guardar_observacion(self, crudo, solicitud, calidad) -> int:
        familias = [v.familia_id for v in solicitud.ventas]
        ventas = [v.ventas for v in solicitud.ventas]
        with self.pool.connection() as c, c.transaction():
            sid = self._solicitud(c, "/v1/observaciones", crudo, solicitud.tienda_id, solicitud.fecha,
                                  calidad.estado)
            self._correcciones(c, sid, calidad)
            # Upsert: inserta lo nuevo, actualiza solo si el valor cambió. RETURNING cuenta ambos.
            n = len(c.execute(
                """
                INSERT INTO observaciones (tienda_id, fecha, familia_id, ventas, solicitud_id)
                SELECT %s, %s, f, v, %s FROM unnest(%s::text[], %s::int[]) AS t(f, v)
                ON CONFLICT (tienda_id, fecha, familia_id) DO UPDATE
                    SET ventas = EXCLUDED.ventas, solicitud_id = EXCLUDED.solicitud_id, actualizada_en = now()
                    WHERE observaciones.ventas IS DISTINCT FROM EXCLUDED.ventas
                RETURNING 1
                """,
                (solicitud.tienda_id, solicitud.fecha, sid, familias, ventas),
            ).fetchall())
            c.execute("UPDATE solicitudes SET registros_guardados = %s WHERE id = %s", (n, sid))
        return n
