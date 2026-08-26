-- Gold: worst-case emissions (closest to the limit) for the report picker.
CREATE OR REFRESH MATERIALIZED VIEW gold_worst_emissions
AS
SELECT
  project_id,
  discipline,
  freq_mhz,
  margin_db,
  status,
  cells
FROM silver_measurements
WHERE discipline IN ('radiated_emissions', 'conducted_emissions')
  AND margin_db IS NOT NULL;
