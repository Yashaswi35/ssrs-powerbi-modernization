-- Reporting layer: datasets for the 2 legacy paginated reports, plus the RLS access table.
-- The paginated reports read these views. Power BI does NOT: it recomputes the same
-- numbers with DAX on the star schema, so the parity check is a real comparison.
SET NOCOUNT ON;
GO

-- Report 1: Top 50 prescribers per territory by total drug cost
CREATE OR ALTER VIEW dw.vw_rpt_top_prescribers AS
WITH agg AS (
    SELECT f.territory_key,
           f.prescriber_key,
           SUM(CAST(f.total_claims AS BIGINT)) AS total_claims,
           SUM(f.total_drug_cost)              AS total_drug_cost,
           COUNT(DISTINCT f.drug_key)          AS drug_count
    FROM dw.fact_prescribing f
    GROUP BY f.territory_key, f.prescriber_key
), ranked AS (
    SELECT a.*,
           ROW_NUMBER() OVER (PARTITION BY a.territory_key
                              ORDER BY a.total_drug_cost DESC, a.prescriber_key) AS cost_rank
    FROM agg a
)
SELECT t.territory_name,
       r.cost_rank,
       p.npi,
       p.prescriber_name,
       p.specialty,
       p.city,
       r.total_claims,
       r.total_drug_cost,
       ROUND(r.total_drug_cost / NULLIF(r.total_claims, 0), 2) AS cost_per_claim,
       r.drug_count
FROM ranked r
JOIN dw.dim_prescriber p ON p.prescriber_key = r.prescriber_key
JOIN dw.dim_territory  t ON t.territory_key  = r.territory_key
WHERE r.cost_rank <= 50;
GO

-- Report 2: Top 25 drugs per territory by total drug cost
CREATE OR ALTER VIEW dw.vw_rpt_top_drugs AS
WITH agg AS (
    SELECT f.territory_key,
           f.drug_key,
           SUM(CAST(f.total_claims AS BIGINT)) AS total_claims,
           SUM(f.total_30day_fills)            AS total_30day_fills,
           SUM(f.total_drug_cost)              AS total_drug_cost,
           COUNT(DISTINCT f.prescriber_key)    AS prescriber_count
    FROM dw.fact_prescribing f
    GROUP BY f.territory_key, f.drug_key
), territory_total AS (
    SELECT territory_key, SUM(total_drug_cost) AS territory_cost
    FROM agg
    GROUP BY territory_key
), ranked AS (
    SELECT a.*,
           ROW_NUMBER() OVER (PARTITION BY a.territory_key
                              ORDER BY a.total_drug_cost DESC, a.drug_key) AS cost_rank
    FROM agg a
)
SELECT t.territory_name,
       r.cost_rank,
       d.brand_name,
       d.generic_name,
       r.total_claims,
       r.total_30day_fills,
       r.total_drug_cost,
       ROUND(r.total_drug_cost / NULLIF(r.total_claims, 0), 2)        AS cost_per_claim,
       r.prescriber_count,
       ROUND(r.total_drug_cost / NULLIF(tt.territory_cost, 0), 4)     AS pct_of_territory_cost
FROM ranked r
JOIN territory_total   tt ON tt.territory_key = r.territory_key
JOIN dw.dim_drug       d  ON d.drug_key       = r.drug_key
JOIN dw.dim_territory  t  ON t.territory_key  = r.territory_key
WHERE r.cost_rank <= 25;
GO

-- Dynamic RLS: which demo user can see which territory
DROP TABLE IF EXISTS dw.security_territory_access;
CREATE TABLE dw.security_territory_access (
    user_principal  NVARCHAR(256) NOT NULL,
    territory_key   INT           NOT NULL REFERENCES dw.dim_territory(territory_key),
    CONSTRAINT pk_security_territory_access PRIMARY KEY (user_principal, territory_key)
);

-- One rep per territory (texas.rep@demo.local, ...) and a regional manager who sees all
INSERT INTO dw.security_territory_access (user_principal, territory_key)
SELECT LOWER(REPLACE(territory_name, N' ', N'')) + N'.rep@demo.local', territory_key
FROM dw.dim_territory
UNION ALL
SELECT N'region.manager@demo.local', territory_key
FROM dw.dim_territory;
GO
