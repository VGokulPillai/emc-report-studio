-- Gold: measurements the report studio consumes.
CREATE OR REFRESH MATERIALIZED VIEW gold_report_measurements
AS
SELECT
  project_id,
  discipline,
  freq_mhz,
  reading,
  limit_value,
  margin_db,
  detector,
  status,
  cells
FROM silver_measurements;
