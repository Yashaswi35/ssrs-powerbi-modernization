-- Populate the star schema from staging
SET NOCOUNT ON;

INSERT INTO dw.dim_territory (state_abbr, territory_name, region_name)
SELECT state_abbr, territory_name, region_name
FROM stg.territory_map;
GO

-- One row per NPI. CMS reports prescriber attributes once per NPI per year,
-- so MAX() only collapses repeats across drug rows.
WITH p AS (
    SELECT Prscrbr_NPI                 AS npi,
           MAX(Prscrbr_Last_Org_Name)  AS last_org_name,
           MAX(Prscrbr_First_Name)     AS first_name,
           MAX(Prscrbr_City)           AS city,
           MAX(Prscrbr_State_Abrvtn)   AS state_abbr,
           MAX(Prscrbr_Type)           AS specialty,
           MAX(Prscrbr_Type_Src)       AS specialty_source
    FROM stg.partd_prescriber_drug
    GROUP BY Prscrbr_NPI
)
INSERT INTO dw.dim_prescriber
    (npi, prescriber_name, last_org_name, first_name, city, state_abbr,
     specialty, specialty_source, territory_key)
SELECT p.npi,
       CONCAT_WS(N', ', p.last_org_name, p.first_name),
       p.last_org_name, p.first_name, p.city, p.state_abbr,
       p.specialty, p.specialty_source, t.territory_key
FROM p
JOIN dw.dim_territory t ON t.state_abbr = p.state_abbr;
GO

INSERT INTO dw.dim_drug (brand_name, generic_name)
SELECT DISTINCT ISNULL(Brnd_Name, N'(unknown)'), ISNULL(Gnrc_Name, N'(unknown)')
FROM stg.partd_prescriber_drug;
GO

INSERT INTO dw.fact_prescribing
    (data_year, prescriber_key, drug_key, territory_key,
     total_claims, total_30day_fills, total_day_supply, total_drug_cost, total_beneficiaries,
     ge65_claims, ge65_30day_fills, ge65_drug_cost, ge65_day_supply, ge65_beneficiaries,
     ge65_suppression_flag, ge65_bene_suppression_flag)
SELECT s.data_year, p.prescriber_key, d.drug_key, p.territory_key,
       s.Tot_Clms, s.Tot_30day_Fills, s.Tot_Day_Suply, s.Tot_Drug_Cst, s.Tot_Benes,
       s.GE65_Tot_Clms, s.GE65_Tot_30day_Fills, s.GE65_Tot_Drug_Cst, s.GE65_Tot_Day_Suply, s.GE65_Tot_Benes,
       s.GE65_Sprsn_Flag, s.GE65_Bene_Sprsn_Flag
FROM stg.partd_prescriber_drug s
JOIN dw.dim_prescriber p ON p.npi = s.Prscrbr_NPI
JOIN dw.dim_drug d
  ON d.brand_name   = ISNULL(s.Brnd_Name, N'(unknown)')
 AND d.generic_name = ISNULL(s.Gnrc_Name, N'(unknown)');
GO
