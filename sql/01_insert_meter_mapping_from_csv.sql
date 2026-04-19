-- Insert the provided active mapping into `meters`.
-- Assumes gateways already exist in table `gateways` (host, port).
-- NOTE: No explicit BEGIN/COMMIT so it runs in DB Browser for SQLite too.

WITH mapping(gateway_host, gateway_port, unit_id, slot_code, description, phase, status) AS (
  VALUES
    ('192.168.1.101', 502, 1,  'P246', 'Nacho',      NULL, 'Activo'),
    ('192.168.1.101', 502, 2,  'P154', 'Oscar',      NULL, 'Activo'),
    ('192.168.1.101', 502, 3,  'P133', 'Asterio',    NULL, 'Activo'),
    ('192.168.1.101', 502, 4,  'P205', 'José',       NULL, 'Activo'),
    ('192.168.1.101', 502, 5,  'P131', 'José María', NULL, 'Activo'),
    ('192.168.1.101', 502, 6,  'P131', 'Valle',      NULL, 'Activo'),
    ('192.168.1.102', 502, 24, 'P318', 'Arancha',    NULL, 'Activo'),
    ('192.168.1.102', 502, 25, 'P361', 'Ben',        NULL, 'Activo'),
    ('192.168.1.103', 502, 2,  'P302', 'Carlos',     NULL, 'Activo')
)
INSERT INTO meters (gateway_id, unit_id, slot_code, description, phase, status, multiplier)
SELECT
  g.id AS gateway_id,
  m.unit_id,
  m.slot_code,
  m.description,
  m.phase,
  m.status,
  1.0 AS multiplier
FROM mapping m
JOIN gateways g
  ON g.host = m.gateway_host
 AND g.port = m.gateway_port
WHERE NOT EXISTS (
  SELECT 1
  FROM meters x
  WHERE x.gateway_id = g.id
    AND x.unit_id = m.unit_id
);
