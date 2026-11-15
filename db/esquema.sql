-- Esquema de la base de datos propia de NovaMercado (separada de la de Airflow).
-- Idempotente: se aplica en cada arranque del servicio sin perder datos.

-- Control de cargas únicas (p. ej. el histórico publicado)
CREATE TABLE IF NOT EXISTS meta (
    clave        text PRIMARY KEY,
    valor        text NOT NULL,
    actualizado  timestamptz NOT NULL DEFAULT now()
);

-- Histórico publicado en el GES (se carga una sola vez)
CREATE TABLE IF NOT EXISTS historico_ventas (
    fecha         date     NOT NULL,
    tienda_id     integer  NOT NULL,
    familia_id    text     NOT NULL,
    ventas        integer  NOT NULL CHECK (ventas >= 0),
    en_promocion  integer  NOT NULL CHECK (en_promocion >= 0),
    PRIMARY KEY (tienda_id, fecha, familia_id)
);

-- Cada solicitud recibida, válida o rechazada, con su cuerpo original
CREATE TABLE IF NOT EXISTS solicitudes (
    id               bigserial    PRIMARY KEY,
    endpoint         text         NOT NULL,
    recibida_en      timestamptz  NOT NULL DEFAULT now(),
    cuerpo           jsonb,                       -- NULL si no era JSON válido
    tienda_id        integer,
    fecha            date,
    estado           text         NOT NULL CHECK (estado IN ('ok', 'corregido', 'advertencia', 'rechazado')),
    detalle_rechazo  text,
    version_modelo   text,
    registros_guardados integer
);
CREATE INDEX IF NOT EXISTS solicitudes_tienda_fecha ON solicitudes (tienda_id, fecha);

-- Correcciones y advertencias aplicadas a cada solicitud (bloque `calidad`)
CREATE TABLE IF NOT EXISTS correcciones (
    id            bigserial  PRIMARY KEY,
    solicitud_id  bigint     NOT NULL REFERENCES solicitudes (id),
    campo         text       NOT NULL,
    accion        text       NOT NULL CHECK (accion IN ('reparar', 'advertir')),
    detalle       text       NOT NULL
);
CREATE INDEX IF NOT EXISTS correcciones_solicitud ON correcciones (solicitud_id);

-- Cada predicción emitida, con la versión del modelo que la produjo
CREATE TABLE IF NOT EXISTS predicciones (
    id                 bigserial  PRIMARY KEY,
    solicitud_id       bigint     NOT NULL REFERENCES solicitudes (id),
    tienda_id          integer    NOT NULL,
    fecha              date       NOT NULL,
    familia_id         text       NOT NULL,
    en_promocion       integer    NOT NULL,
    venta_esperada     double precision NOT NULL,
    cantidad_sugerida  integer    NOT NULL CHECK (cantidad_sugerida >= 0),
    version_modelo     text       NOT NULL
);
CREATE INDEX IF NOT EXISTS predicciones_tienda_fecha ON predicciones (tienda_id, fecha, familia_id);

-- Ventas reales observadas. La llave primaria garantiza la idempotencia.
CREATE TABLE IF NOT EXISTS observaciones (
    tienda_id       integer      NOT NULL,
    fecha           date         NOT NULL,
    familia_id      text         NOT NULL,
    ventas          integer      NOT NULL CHECK (ventas >= 0),
    solicitud_id    bigint       NOT NULL REFERENCES solicitudes (id),
    creada_en       timestamptz  NOT NULL DEFAULT now(),
    actualizada_en  timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (tienda_id, fecha, familia_id)
);

-- Ventas conocidas: observaciones y, donde no las hay, el histórico
CREATE OR REPLACE VIEW ventas_conocidas AS
SELECT o.fecha, o.tienda_id, o.familia_id, o.ventas, 'observacion'::text AS origen
FROM observaciones o
UNION ALL
SELECT h.fecha, h.tienda_id, h.familia_id, h.ventas, 'historico'::text AS origen
FROM historico_ventas h
WHERE NOT EXISTS (
    SELECT 1 FROM observaciones o
    WHERE o.tienda_id = h.tienda_id AND o.fecha = h.fecha AND o.familia_id = h.familia_id
);

-- Datos para reentrenar: ventas conocidas + promoción del día.
-- Las observaciones no traen promoción: se toma la de la última solicitud de
-- predicción de ese día (es la que el modelo usó); NULL si nunca se pidió.
CREATE OR REPLACE VIEW ventas_entrenamiento AS
SELECT v.fecha, v.tienda_id, v.familia_id, v.ventas,
       COALESCE(h.en_promocion, p.en_promocion) AS en_promocion,
       v.origen
FROM ventas_conocidas v
LEFT JOIN historico_ventas h
       ON h.tienda_id = v.tienda_id AND h.fecha = v.fecha AND h.familia_id = v.familia_id
LEFT JOIN LATERAL (
    SELECT pr.en_promocion FROM predicciones pr
    WHERE pr.tienda_id = v.tienda_id AND pr.fecha = v.fecha AND pr.familia_id = v.familia_id
    ORDER BY pr.id DESC LIMIT 1
) p ON true;
