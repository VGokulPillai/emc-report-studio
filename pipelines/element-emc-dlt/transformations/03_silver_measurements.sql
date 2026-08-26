-- Silver: typed, report-ready measurement rows.
CREATE OR REFRESH MATERIALIZED VIEW silver_measurements
AS
SELECT
  project_id,
  discipline,
  row_index,
  test_id,
  CAST(freq_mhz AS DOUBLE) AS freq_mhz,
  CAST(reading AS DOUBLE) AS reading,
  CAST(limit_value AS DOUBLE) AS limit_value,
  CAST(margin_db AS DOUBLE) AS margin_db,
  detector,
  polarisation,
  conductor,
  upper(status) AS status,
  cells
FROM bronze_measurements
WHERE project_id IS NOT NULL
  AND discipline IS NOT NULL;
