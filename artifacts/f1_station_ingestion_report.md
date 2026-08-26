# Feature 1 Station Ingestion Report

## Run

- Provider: `VINFAST_OFFICIAL`
- Upstream metadata status: HTTP 200
- Upstream bulk status: HTTP 200
- Generation: `743`
- Bulk checksum (SHA-256): `6aae7ea7e20147f124809d4fd5bdf566ca59f8f457f45dab804b1d2eb4f7bdd5`
- Dataset retrieved at: `2026-08-22T07:34:19.546055+00:00`
- Successful first-run elapsed time: `48.945s`
- Same-generation rerun: `NOOP`, `0` rows written, `7.03s`

## Record Accounting

| Metric | Count |
|---|---:|
| Raw records | 66,902 |
| Non-car-charging records filtered | 42,960 |
| Non-published charging records filtered | 23 |
| Non-public records filtered | 0 |
| Invalid required-field records rejected | 0 |
| Invalid-coordinate records rejected | 0 |
| Duplicate accepted external IDs | 0 |
| Normalized locations | 23,919 |
| Active locations | 23,919 |

## Detail Quality

| Quality | Count |
|---|---:|
| `VERIFIED` | 0 |
| `PARTIAL` | 23,919 |
| `UNVERIFIED` | 0 |

Bulk-only records remain `PARTIAL`; connector type, power and availability were
not fabricated. Optional technical-detail hydration is a separate background job.

## Database Acceptance

- Provider distribution: `VINFAST_OFFICIAL = 23,919` active locations.
- Duplicate `(provider, external_id)` groups: `0`.
- Latitude outside `[-90, 90]`: `0`.
- Longitude outside `[-180, 180]`: `0`.
- Active locations with null coordinate/geography: `0`.
- Active locations with missing raw payload: `0`.
- Active locations with missing retrieval timestamp: `0`.
- Active dataset versions: `1`.
- Source last-modified timestamp and `valid_until` are present.

## Remediation During Rollout

The first attempt exceeded the five-minute execution limit and rolled back fully.
The repository was issuing one location lookup per input row. It now preloads the
provider's existing locations once and retains the same transactional upsert and
inactive-lifecycle behavior. Catalog/graph repository tests passed before the
successful production-dialect rerun.
