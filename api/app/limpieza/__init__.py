"""Defensa del contrato: convierte la entrada cruda en una solicitud limpia o la rechaza.

Cada función devuelve (solicitud_limpia, observaciones_de_calidad) o lanza `Rechazo`.
No depende de FastAPI: se prueba como un módulo de Python normal.
"""

from app.limpieza.base import Bitacora, Contexto, Rechazo
from app.limpieza.solicitudes import limpiar_observacion, limpiar_prediccion

__all__ = ["Bitacora", "Contexto", "Rechazo", "limpiar_observacion", "limpiar_prediccion"]
