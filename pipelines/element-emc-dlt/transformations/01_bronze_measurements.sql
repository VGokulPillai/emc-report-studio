-- Bronze: raw EMC measurements from the lab Gold landing table.
CREATE OR REFRESH MATERIALIZED VIEW bronze_measurements
AS
SELECT
  *,
  current_timestamp() AS ingested_at
FROM serverless_stable_1acr1x_catalog.emc_gold.measurements;
