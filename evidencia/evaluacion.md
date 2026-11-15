# Evaluación de operación simulada

Periodo: 2026-03-01 + 28 días · cambio de demanda ×1.3 desde el día 14 · 30% de solicitudes con defectos fuera del catálogo · semilla 7

## Resultado

| Métrica | Valor |
|---|---|
| Predicciones evaluadas | 3204 |
| Errores de contrato | **0** |
| Costo del servicio | 107,669 |
| Costo del baseline | 176,468 |
| Ahorro frente al baseline | **39.0%** |
| MAE de la venta esperada | 46.11 |

## Por semana

| Semana | Costo | Baseline | Ahorro | MAE |
|---|---|---|---|---|
| 1 | 20,565 | 30,361 | 32.3% | 36.4 |
| 2 | 20,149 | 35,386 | 43.1% | 36.7 |
| 3 | 33,844 | 61,447 | 44.9% | 56.6 |
| 4 | 33,111 | 49,274 | 32.8% | 53.0 |

## Eventos

| Día | Evento | Detalle |
|---|---|---|
| 2026-03-08 | reentrenar | {"segundos": 70, "adopcion_seg": 0, "estado": "exitoso", "promovido": true, "version": "2", "motivo": "Costo en validación 20 949 vs 20 565 del vigente (+1.9%, 7 días); se adopta el modelo con datos más recientes", "version_candidata": "2"} |
| 2026-03-10 | mlflow_detenido | {"degradado_seg": 14.3} |
| 2026-03-12 | mlflow_iniciado | {"ok_seg": 12.3} |
| 2026-03-15 | reentrenar | {"segundos": 51, "adopcion_seg": 2, "estado": "exitoso", "promovido": true, "version": "3", "motivo": "Costo en validación 19 446 vs 20 149 del vigente (-3.5%, 7 días); se adopta el modelo con datos más recientes", "version_candidata": "3"} |
| 2026-03-18 | down_up | {"ok_seg": 30.6, "total_seg": 59} |
| 2026-03-22 | reentrenar | {"segundos": 88, "adopcion_seg": 6, "estado": "exitoso", "promovido": true, "version": "4", "motivo": "Costo en validación 34 103 vs 33 844 del vigente (+0.8%, 7 días); se adopta el modelo con datos más recientes", "version_candidata": "4"} |

## Calidad de las respuestas

```
{
 "pred ok": 184,
 "pred corregido": 69,
 "pred advertencia": 14,
 "obs ok": 190,
 "obs advertencia": 3,
 "obs corregido": 74
}
```

## Defectos enviados (no están en el catálogo)

```
{
 "pred:clave_tienda": 10,
 "pred:promo_nula": 5,
 "pred:fecha": 10,
 "pred:envuelta": 13,
 "obs:familia_nombre": 16,
 "obs:miles": 16,
 "pred:tienda_texto": 8,
 "pred:promo_formato": 5,
 "obs:fecha": 20,
 "obs:clave_ventas": 19,
 "pred:familias_objeto": 10,
 "obs:decimal_coma": 17,
 "pred:campo_extra": 5,
 "pred:clave_promo": 10,
 "pred:familia_nombre": 7
}
```

## Versiones del modelo que respondieron

```
{"1": 63, "2": 64, "3": 70, "4": 70}
```

## Errores de contrato

Ninguno.
