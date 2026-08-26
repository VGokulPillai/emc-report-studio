CREATE OR REFRESH MATERIALIZED VIEW bronze_projects
AS
SELECT
  *,
  current_timestamp() AS ingested_at
FROM serverless_stable_1acr1x_catalog.emc_gold.projects;
