"""Criterio explícito y automatizado para decidir si un candidato reemplaza al vigente.

Ambos modelos se evalúan con la métrica de negocio (costo de la cantidad sugerida) sobre
la MISMA ventana: días que ninguno de los dos vio al entrenar. Para el vigente son los
días posteriores a sus datos; el candidato se evalúa con su versión entrenada antes de
esa ventana.

Por qué NO-REGRESIÓN y no "mejora mínima": la versión del candidato que se evalúa se
entrena antes de la ventana, igual que el vigente, así que en la comparación ninguno ve
los días nuevos. La ventaja real del candidato está en la versión que se despliega,
reentrenada con todo (incluido un posible cambio de demanda), y eso no se puede medir
sin días futuros. Exigir una mejora volvería la promoción casi aleatoria y retrasaría la
adaptación. Por eso el candidato reemplaza al vigente salvo que sea claramente peor: la
comparación protege contra un entrenamiento roto o degradado.

Reglas, en orden (la primera que aplica decide):
  1. El candidato debe ser válido (métricas finitas, sugerencias enteras ≥ 0).
  2. El candidato debe costar menos que el baseline en la ventana (control de cordura).
  3. Si no hay vigente, o no se puede evaluar, se promueve.
  4. Hacen falta al menos DIAS_MINIMOS días nuevos para comparar con el vigente.
  5. Se promueve si su costo no supera al del vigente en más de TOLERANCIA.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DIAS_MINIMOS = 7
# 2 %: el candidato evaluado tiene 28 días menos de datos que el vigente (los de calibración);
# por encima de este margen la diferencia ya no se explica por eso ni por ruido.
TOLERANCIA = 0.02


@dataclass
class Evaluacion:
    costo_candidato: float
    costo_baseline: float
    costo_vigente: float | None  # None: no hay vigente o no se pudo evaluar
    dias_evaluacion: int
    version_vigente: str | None = None
    candidato_valido: bool = True
    problema_candidato: str = ""


@dataclass
class Decision:
    promover: bool
    motivo: str


def _n(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def decidir(ev: Evaluacion, tolerancia: float = TOLERANCIA, dias_minimos: int = DIAS_MINIMOS) -> Decision:
    if not ev.candidato_valido or not math.isfinite(ev.costo_candidato):
        return Decision(False, f"Candidato inválido: {ev.problema_candidato or 'costo no finito'}")
    if ev.costo_candidato >= ev.costo_baseline:
        return Decision(False, f"El candidato no supera al baseline: costo {_n(ev.costo_candidato)} "
                               f"vs {_n(ev.costo_baseline)}")
    if ev.version_vigente is None:
        return Decision(True, f"No hay modelo vigente; el candidato supera al baseline "
                              f"({_n(ev.costo_candidato)} vs {_n(ev.costo_baseline)})")
    if ev.costo_vigente is None or not math.isfinite(ev.costo_vigente):
        return Decision(True, f"El vigente (versión {ev.version_vigente}) no se pudo evaluar; "
                              f"el candidato supera al baseline")
    if ev.dias_evaluacion < dias_minimos:
        return Decision(False, f"Solo {ev.dias_evaluacion} días nuevos desde el vigente; "
                               f"se necesitan {dias_minimos} para comparar")
    cambio = ev.costo_candidato / ev.costo_vigente - 1 if ev.costo_vigente > 0 else 0.0
    texto = (f"Costo en validación {_n(ev.costo_candidato)} vs {_n(ev.costo_vigente)} del vigente "
             f"({cambio:+.1%}, {ev.dias_evaluacion} días)")
    if cambio <= tolerancia:
        return Decision(True, texto + "; se adopta el modelo con datos más recientes")
    return Decision(False, texto + f"; empeora más de {tolerancia:.0%}, se conserva el vigente")
