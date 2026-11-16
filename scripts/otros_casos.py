"""Evidencia de rechazos (422) y de los endpoints de administración.

Uso:  python scripts/otros_casos.py [--url http://localhost:8000]
Escribe evidencia/respuestas/otros_casos.json. Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

FAM = [{"familia_id": "abarrotes", "en_promocion": 0}]
CASOS = [
    ("Tienda inexistente", "POST", "/v1/prediccion", {"tienda_id": 99, "fecha": "2026-03-29", "familias": FAM}, None),
    ("Fecha imposible", "POST", "/v1/prediccion", {"tienda_id": 5, "fecha": "2026-02-30", "familias": FAM}, None),
    ("Fecha anterior a la apertura de la tienda", "POST", "/v1/prediccion",
     {"tienda_id": 10, "fecha": "2025-01-10", "familias": FAM}, None),
    ("Campos en conflicto (tienda_id y tienda)", "POST", "/v1/prediccion",
     {"tienda_id": 5, "tienda": 3, "fecha": "2026-03-29", "familias": FAM}, None),
    ("Ninguna familia válida", "POST", "/v1/prediccion",
     {"tienda_id": 5, "fecha": "2026-03-29", "familias": [{"familia_id": "ropa", "en_promocion": 1}]}, None),
    ("Cuerpo que no es JSON", "POST", "/v1/prediccion", None, b"{tienda_id: 5"),
    ("Observación sin registros válidos", "POST", "/v1/observaciones",
     {"tienda_id": 5, "fecha": "2026-03-28", "ventas": [{"familia_id": "bebe", "ventas": -3}]}, None),
    ("Varios problemas a la vez", "POST", "/v1/prediccion",
     {"Tienda": "T05", "date": "29/03/2026", "items": [{"familia": "LÁCTEOS", "promo": "2"},
                                                       {"familia_id": "limpiesa", "en_promocion": None}],
      "canal": "pos"}, None),
    ("Modelo vigente", "GET", "/modelo", None, None),
    ("Estado del servicio", "GET", "/health", None, None),
    ("Ejecución de reentrenamiento desconocida", "GET", "/admin/reentrenar/rt_no_existe", None, None),
]


def pedir(url: str, metodo: str, ruta: str, cuerpo, crudo):
    datos = crudo if crudo is not None else (None if cuerpo is None else json.dumps(cuerpo).encode())
    req = urllib.request.Request(url + ruta, data=datos, method=metodo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--salida", default="evidencia/respuestas/otros_casos.json")
    a = ap.parse_args()
    salida = []
    for nombre, metodo, ruta, cuerpo, crudo in CASOS:
        s, r = pedir(a.url, metodo, ruta, cuerpo, crudo)
        salida.append({"caso": nombre, "solicitud": f"{metodo} {ruta}",
                       "cuerpo": cuerpo if crudo is None else crudo.decode(), "status": s, "respuesta": r})
        resumen = r.get("detail") or (r.get("calidad", {}).get("estado") if "calidad" in r else r)
        print(f"{s}  {nombre}: {str(resumen)[:110]}")
    with open(a.salida, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
