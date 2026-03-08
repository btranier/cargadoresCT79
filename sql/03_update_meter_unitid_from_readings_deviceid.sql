-- Update `meters.unit_id` so it becomes globally unique using `readings.deviceid`.
-- Preserve original Modbus unit_id in `meters.slot_id`.
--
-- IMPORTANT:
-- - This script targets a `readings.deviceid` column (as requested).
-- - Run once. If `slot_id` already exists, skip the ALTER TABLE line.
-- - No explicit BEGIN/COMMIT so it runs in DB Browser for SQLite too.

-- 1) Preserve current unit_id in slot_id.
ALTER TABLE meters ADD COLUMN slot_id INTEGER;

UPDATE meters
SET slot_id = unit_id
WHERE slot_id IS NULL;

-- 2) Build deterministic global IDs from readings.deviceid and update meters.unit_id.
WITH device_map AS (
  SELECT
    r.meter_id,
    MIN(TRIM(r.deviceid)) AS deviceid
  FROM readings r
  WHERE r.meter_id IS NOT NULL
    AND COALESCE(TRIM(r.deviceid), '') <> ''
  GROUP BY r.meter_id
),
ranked AS (
  SELECT
    meter_id,
    deviceid,
    DENSE_RANK() OVER (ORDER BY deviceid) AS new_unit_id
  FROM device_map
)
UPDATE meters
SET unit_id = (
  SELECT ranked.new_unit_id
  FROM ranked
  WHERE ranked.meter_id = meters.id
)
WHERE id IN (SELECT meter_id FROM ranked);
