# openIMIS Backend Legacy Individual module

Stores archived PSSN historical person and household data, fully isolated from
the live `individual` module. Designed to ingest the paired PSSN CSV export
and expose the archive for search, audit, and (phase 2) matching/promotion
into the live system.

## ORM mapping

- `legacy_individual_legacyimportbatch`,
  `legacy_individual_historicallegacyimportbatch` → `LegacyImportBatch`
- `legacy_individual_legacygroup`,
  `legacy_individual_historicallegacygroup` → `LegacyGroup`
- `legacy_individual_legacyindividual`,
  `legacy_individual_historicallegacyindividual` → `LegacyIndividual`
- `legacy_individual_legacygroupindividual`,
  `legacy_individual_historicallegacygroupindividual` →
  `LegacyGroupIndividual`

## GraphQL queries

- `legacyIndividuals`
- `legacyIndividual`
- `legacyGroups`
- `legacyGroup`
- `legacyGroupIndividuals`
- `legacyImportBatches`
- `legacyImportBatch`

## GraphQL mutations

- `createLegacyImportBatch` — kicks off the PSSN paired-CSV workflow

## REST endpoints

- `POST /legacy_individual/import_pssn/` — multipart upload of the two PSSN
  CSVs (`household_file`, `member_file`)

## Services

- `LegacyImportBatchService` — create batch, persist files, trigger
  workflow, finalize
- `PssnNormalizationService` — name trimming, date/code normalization,
  gender/disability decoding, relationship-code → role mapping
- `LegacyIndividualService`, `LegacyGroupService` — read-mostly search
  helpers

## Configuration

Permission keys (set in `apps.DEFAULT_CONFIG`):

- `gql_legacy_individual_search_perms`
- `gql_legacy_individual_create_perms`
- `gql_legacy_individual_update_perms`
- `gql_legacy_individual_delete_perms`
- `gql_legacy_group_search_perms`
- `gql_legacy_group_create_perms`
- `gql_legacy_group_update_perms`
- `gql_legacy_import_execute_perms`

Behavior flags:

- `legacy_read_only_default` (default `True`)
- `legacy_preserve_uploaded_file` (default `True`)
- `legacy_resolve_facility_against_tblhf` (default `True`)

## Boundaries

- The module never writes to `individual_individual` or `individual_group`.
- Cross-references to live records are deferred to phase 2 via separate
  `LegacyMatchLink` / `LegacyPromotionRecord` tables (not present in MVP).
- See `docs/legacy-individual-module/` in this repo for the full design,
  schema, and PSSN column mapping contract.
