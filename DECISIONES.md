# DECISIONES

Decisiones técnicas y de producto del servicio de pronóstico de NovaMercado, con sus
alternativas y justificación. Se actualiza en cada fase del proyecto.

---

## 1. Política ante problemas en los datos de entrada

### Principio

| Acción | Cuándo | Efecto en `calidad` |
|---|---|---|
| **Reparar** | La interpretación es **única** y no cambia el significado del dato. | `corregido` |
| **Advertir** | Se respondió **suponiendo algo**; la respuesta dice qué se supuso. | `advertencia` |
| **Rechazar** | No se puede saber **qué tienda o qué fecha** se pide, o responder obligaría a **inventar** datos. | HTTP 422 con `detail` |

Las reglas se definen por **tipo de problema** (nombre de campo, número, fecha,
identificador, familia, duplicado, faltante, rango) y no por ejemplo concreto. Por eso se
aplican igual a problemas que no están en el catálogo.

**Alternativa descartada: rechazar todo lo que no cumpla el contrato.** Es más simple, pero
la dirección de operaciones pidió explícitamente un servicio *que no se detenga* por estos
problemas. **Alternativa descartada: reparar todo "lo mejor posible".** Viola el requisito
de *no inventar datos* y oculta los supuestos.

### Tabla de políticas

| Tipo de problema | Ejemplos | Política | Razón |
|---|---|---|---|
| Nombre de campo distinto | `tienda`, `tiendaId`, `id_tienda`, `store_id` (E07) | Reparar | Sinónimo conocido o mismas palabras en otro orden o formato: inequívoco. |
| Nombre de campo con error de tipeo | `fehca` | Advertir | Se supone el campo más parecido (similitud ≥ 0.8 y sin empate). |
| Dos campos que significan lo mismo con valores distintos | `tienda_id: 5` y `tienda: 1` | Rechazar | No hay forma de saber cuál es el correcto. |
| Campo no reconocido | `canal: "web"` | Advertir | Se ignora; podría ser información que no se está usando. |
| Cuerpo envuelto o en lista de un elemento | `{"solicitud": {...}}`, `[{...}]` | Reparar | El contenido es inequívoco. |
| Identificador de tienda como texto, con prefijo o por nombre | `"5"`, `"T05"`, `5.0`, `"NovaMercado Mixco"` (E01) | Reparar | Un solo número o un nombre único. Primero se busca por nombre: `"NovaMercado Zona 10"` es la tienda 1. |
| Tienda inexistente, ambigua o ausente | `99`, `"T5-2"`, `null` | Rechazar | Sin tienda no hay a quién pronosticar. |
| Número como texto o con formato | `"9"`, `8.0`, `"1,234"`, `"812,0"`, `"1.234,5"` (E03, E10) | Reparar | Regla general: si hay `,` y `.`, el último es el decimal; un separador seguido de exactamente 3 dígitos es de miles; si no, es decimal. |
| Cantidad no entera | `2.5`, `"12,5"` | Advertir | Unidades y promociones son enteras: se redondea y se avisa. |
| Fecha en otro formato no ambiguo | `17/11/2025`, `2025-11-17T00:00:00`, `20251117`, `17 nov 2025` (E04) | Reparar | Una sola fecha posible. |
| Fecha ambigua | `05/11/2025` | Advertir | Se supone día/mes, la convención en Guatemala. |
| Fecha imposible, ausente o fuera de rango | `2025-02-30`, `mañana`, `1800-01-01` | Rechazar | Sin fecha válida no hay qué pronosticar. |
| Fecha anterior a la apertura de la tienda | tienda 10 antes del 2025-03-15 | Rechazar | No existían ventas. |
| Fecha posterior al calendario de feriados | 2027-03-01 | Advertir | Se supone un día sin feriados. |
| Familia escrita de otra forma | `LÁCTEOS`, `lacteos `, `Frutas y Verduras`, `lacteo` (E02) | Reparar | Igualdad tras normalizar mayúsculas, acentos, espacios, conectores ("y", "de") y singular/plural, contra el id **y** el nombre del catálogo. |
| Familia con error de tipeo | `abarotes` | Advertir | Se supone la familia más parecida (similitud ≥ 0.8 y sin empate). |
| Familia inexistente | `ropa` | Advertir y omitir | No se inventa. El resto de la solicitud se responde. |
| Familia repetida con el mismo valor | | Reparar | Se usa una vez. |
| Familia repetida con valores distintos | `abarrotes` con 0 y con 3 (E06) | Advertir | Se usa el **último** valor: en flujos de datos, el último envío suele ser la corrección. |
| Faltan familias que la tienda vende (predicción) | llegan 10 de 12 (E05) | Advertir | Se agregan con `en_promocion = 0`, el valor más frecuente en el histórico, porque el inventario necesita todas. |
| Promoción ausente, nula, negativa o ilegible | `null`, `-2`, `"muchas"` | Advertir | Se supone 0. |
| Ventas negativas (observación) | `-4` (E08) | Advertir y **no guardar** ese registro | Son devoluciones mal registradas: la venta real es desconocida y guardarla como 0 sería inventar. El resto de la observación se guarda. |
| Ventas ausentes o ilegibles (observación) | `null`, `"n/d"` | Advertir y no guardar | Igual que el caso anterior. |
| Envío repetido de la misma observación | (E09) | Aceptar | Idempotente: `registros_guardados = 0`. |
| Nada utilizable | todas las familias inválidas | Rechazar | No hay nada que responder. |
| Faltan ventas recientes en la base (lo detecta la predicción) | sin observación del día anterior | Advertir | Se usa la historia disponible y se informa. |

### Implementación

- `api/app/limpieza/` es Python puro, sin FastAPI: `texto.py` (normalización),
  `valores.py` (números, ids, fechas, familias), `campos.py` (nombres de campo) y
  `solicitudes.py` (las políticas).
- Los endpoints no validan la entrada con Pydantic estricto. Un 422 genérico impediría
  reparar o advertir. Pydantic valida la solicitud **ya limpia** y las respuestas.
- `Calidad` deriva su `estado` de las acciones (`advertir` > `reparar` > `ok`) y rechaza
  combinaciones incoherentes.
- Las solicitudes rechazadas también se registran.
- No se usa el reloj del sistema. El rango de fechas válido es el calendario de
  `feriados.csv` con un año de margen hacia cada lado.

---

## 2. Información que usa el modelo al predecir

Solo información disponible **antes** de la fecha pronosticada:

- **Ventas pasadas** de la misma tienda y familia: rezagos de 1 a 7, 14, 21 y 28 días;
  medias de 7 y 28 días; desviación de 28 días; mediana y media del mismo día de la
  semana en las 4 semanas previas.
- **Calendario:** día de la semana, día del mes, mes, día del año, fin de mes. El EDA
  mostró picos los días 15 y 31 (quincena).
- **Fechas especiales** que aplican a la tienda: el feriado `nacional`, o el de su ciudad.
  Se considera hoy, ayer y mañana, por el efecto de víspera.
- **Promociones del día**, recibidas en la solicitud.
- **Tienda:** id, tipo y días desde la apertura (por la tienda 10).

La misma función (`ml/features.py`) calcula las features en entrenamiento y en el
servicio. Una prueba verifica que una solicitud aislada produce exactamente las mismas
features que la fila de entrenamiento. Otra verifica que alterar ventas del mismo día o
posteriores no cambia nada.

**Alternativa descartada: usar solo calendario y promociones.** El nivel reciente es, por
mucho, lo más predictivo, y además permite adaptarse a cambios en la demanda.

---

## 3. Elección de la cantidad sugerida

El costo es asimétrico y distinto por familia. Si se conociera la distribución de la
demanda, la cantidad óptima sería su cuantil `q* = c_faltante / (c_faltante + c_sobrante)`
(problema del vendedor de periódicos).

**Decisión:** `cantidad_sugerida = redondear(venta_esperada × factor_familia)`. El factor
de cada familia se elige en una grilla de 0.50 a 3.00 minimizando el **costo real** en un
periodo de calibración de 28 días que el modelo no vio. Es la versión empírica de `q*`,
sin suponer una distribución.

En febrero de 2026, este ajuste baja el costo un 27% frente a sugerir la venta esperada.
Los factores siguen al cuantil crítico: licores 1.47 (q* = 0.95), panadería 0.86 (q* = 0.29).

**Alternativas:**
- Regresión cuantílica con un modelo por familia: 12 modelos más que mantener.
- Suponer una distribución Poisson o normal: los residuos tienen más dispersión que una
  Poisson.

---

## 4. Modelos

- **Baseline:** mediana de las ventas del mismo día de la semana en las 4 semanas previas.
- **Modelo de ML:** LightGBM con objetivo Poisson, apropiado para conteos no negativos
  con escalas muy distintas.
- **Partición temporal:** entrenamiento, luego 28 días de calibración (early stopping y
  factores), luego 28 días de prueba (métricas). El modelo desplegado se reentrena con
  todos los datos y el mismo número de iteraciones.

| Prueba (febrero 2026) | MAE | WAPE | Costo |
|---|---|---|---|
| Baseline | 47.2 | 22.1% | 132 480 |
| LightGBM | 37.3 | 17.5% | **88 133** (−33.5%) |

---

## 5. Persistencia

- **Base propia:** PostgreSQL 17.6, en un contenedor separado del de Airflow, con volumen
  nombrado (`db_datos`). La información sobrevive a `docker compose down` y `up`.
- **El esquema lo aplica el servicio al arrancar** (`db/esquema.sql`, idempotente) y no
  `docker-entrypoint-initdb.d`. Así un cambio de esquema se aplica también sobre un volumen
  existente. Un *advisory lock* evita que dos procesos inicialicen a la vez.
- **El histórico se carga una sola vez** con `COPY`. La marca `meta.historico_cargado` evita
  repetir la carga al volver a levantar.
- **Tablas:**

  | Tabla | Contenido |
  |---|---|
  | `solicitudes` | Toda solicitud, incluidas las rechazadas, con su cuerpo original (`jsonb`), estado y versión del modelo. |
  | `correcciones` | El bloque `calidad` de cada solicitud. |
  | `predicciones` | Una fila por familia, con la versión del modelo y la promoción usada. |
  | `observaciones` | Ventas reales, con llave `(tienda_id, fecha, familia_id)`. |
  | `historico_ventas` | El histórico publicado. |

- **Idempotencia:** *upsert* sobre la llave de `observaciones`. Se inserta lo nuevo y se
  actualiza solo si el valor cambió. `RETURNING` cuenta ambos casos, que es exactamente
  `registros_guardados`.
- **Corrección de una observación:** si llega un valor distinto para el mismo día, tienda
  y familia, prevalece el último. Se registra la solicitud que lo cambió (`solicitud_id`,
  `actualizada_en`).
- **Histórico y observaciones en tablas separadas,** unidas por la vista `ventas_conocidas`
  (la observación prevalece). La vista `ventas_entrenamiento` agrega la promoción: las
  observaciones no la traen, así que se toma la de la última solicitud de predicción de ese
  día, que es la que el modelo usó.
- **Si la base no responde:** las operaciones que la necesitan responden 503 y `/health`
  pasa a `degradado`. El pool verifica cada conexión antes de usarla, así que el servicio
  se recupera solo cuando la base vuelve.

---

## 6. Criterio de reemplazo del modelo

*(Fase 5–6: pendiente.)*
