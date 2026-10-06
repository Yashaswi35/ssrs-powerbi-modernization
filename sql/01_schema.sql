-- Staging and star schema for CMS Part D prescriber reporting (Azure SQL Database)
SET NOCOUNT ON;
IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg');
GO
IF SCHEMA_ID('dw') IS NULL EXEC('CREATE SCHEMA dw');
GO

DROP TABLE IF EXISTS dw.security_territory_access;
DROP TABLE IF EXISTS dw.fact_prescribing;
DROP TABLE IF EXISTS dw.dim_prescriber;
DROP TABLE IF EXISTS dw.dim_drug;
DROP TABLE IF EXISTS dw.dim_territory;
DROP TABLE IF EXISTS stg.partd_prescriber_drug;
DROP TABLE IF EXISTS stg.territory_map;
DROP TABLE IF EXISTS stg.source_manifest;
GO

-- ---------- Staging ----------
CREATE TABLE stg.territory_map (
    state_abbr      CHAR(2)       NOT NULL PRIMARY KEY,
    territory_name  NVARCHAR(50)  NOT NULL,
    region_name     NVARCHAR(50)  NOT NULL
);

CREATE TABLE stg.source_manifest (
    state_abbr     CHAR(2) NOT NULL PRIMARY KEY,
    rows_written   INT     NOT NULL,
    rows_expected  INT     NULL
);

CREATE TABLE stg.partd_prescriber_drug (
    data_year              SMALLINT        NOT NULL,
    Prscrbr_NPI            NVARCHAR(20)    NOT NULL,
    Prscrbr_Last_Org_Name  NVARCHAR(200)   NULL,
    Prscrbr_First_Name     NVARCHAR(100)   NULL,
    Prscrbr_City           NVARCHAR(100)   NULL,
    Prscrbr_State_Abrvtn   NVARCHAR(10)    NULL,
    Prscrbr_State_FIPS     NVARCHAR(10)    NULL,
    Prscrbr_Type           NVARCHAR(150)   NULL,
    Prscrbr_Type_Src       NVARCHAR(100)   NULL,
    Brnd_Name              NVARCHAR(200)   NULL,
    Gnrc_Name              NVARCHAR(200)   NULL,
    Tot_Clms               INT             NULL,
    Tot_30day_Fills        DECIMAL(14,2)   NULL,
    Tot_Day_Suply          INT             NULL,
    Tot_Drug_Cst           DECIMAL(16,2)   NULL,
    Tot_Benes              INT             NULL,   -- NULL when CMS suppresses (<11 beneficiaries)
    GE65_Sprsn_Flag        NVARCHAR(10)    NULL,
    GE65_Tot_Clms          INT             NULL,
    GE65_Tot_30day_Fills   DECIMAL(14,2)   NULL,
    GE65_Tot_Drug_Cst      DECIMAL(16,2)   NULL,
    GE65_Tot_Day_Suply     INT             NULL,
    GE65_Bene_Sprsn_Flag   NVARCHAR(10)    NULL,
    GE65_Tot_Benes         INT             NULL
);
GO

-- ---------- Star schema ----------
CREATE TABLE dw.dim_territory (
    territory_key   INT IDENTITY(1,1) PRIMARY KEY,
    state_abbr      CHAR(2)       NOT NULL UNIQUE,
    territory_name  NVARCHAR(50)  NOT NULL,
    region_name     NVARCHAR(50)  NOT NULL
);

CREATE TABLE dw.dim_prescriber (
    prescriber_key    INT IDENTITY(1,1) PRIMARY KEY,
    npi               VARCHAR(10)    NOT NULL UNIQUE,
    prescriber_name   NVARCHAR(310)  NULL,
    last_org_name     NVARCHAR(200)  NULL,
    first_name        NVARCHAR(100)  NULL,
    city              NVARCHAR(100)  NULL,
    state_abbr        CHAR(2)        NOT NULL,
    specialty         NVARCHAR(150)  NULL,
    specialty_source  NVARCHAR(100)  NULL,
    territory_key     INT            NOT NULL REFERENCES dw.dim_territory(territory_key)
);

CREATE TABLE dw.dim_drug (
    drug_key      INT IDENTITY(1,1) PRIMARY KEY,
    brand_name    NVARCHAR(200) NOT NULL,
    generic_name  NVARCHAR(200) NOT NULL,
    CONSTRAINT uq_dim_drug UNIQUE (brand_name, generic_name)
);

CREATE TABLE dw.fact_prescribing (
    data_year                 SMALLINT       NOT NULL,
    prescriber_key            INT            NOT NULL REFERENCES dw.dim_prescriber(prescriber_key),
    drug_key                  INT            NOT NULL REFERENCES dw.dim_drug(drug_key),
    territory_key             INT            NOT NULL REFERENCES dw.dim_territory(territory_key),
    total_claims              INT            NULL,
    total_30day_fills         DECIMAL(14,2)  NULL,
    total_day_supply          INT            NULL,
    total_drug_cost           DECIMAL(16,2)  NULL,
    total_beneficiaries       INT            NULL,
    ge65_claims               INT            NULL,
    ge65_30day_fills          DECIMAL(14,2)  NULL,
    ge65_drug_cost            DECIMAL(16,2)  NULL,
    ge65_day_supply           INT            NULL,
    ge65_beneficiaries        INT            NULL,
    ge65_suppression_flag     NVARCHAR(10)   NULL,
    ge65_bene_suppression_flag NVARCHAR(10)   NULL
);
CREATE CLUSTERED COLUMNSTORE INDEX cci_fact_prescribing ON dw.fact_prescribing;
GO

-- Validation history is kept across runs
IF OBJECT_ID('dw.validation_results') IS NULL
CREATE TABLE dw.validation_results (
    run_id          INT            NOT NULL,
    check_name      NVARCHAR(100)  NOT NULL,
    expected_value  DECIMAL(20,2)  NULL,
    actual_value    DECIMAL(20,2)  NULL,
    status          VARCHAR(4)     NOT NULL,
    run_at          DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
GO
