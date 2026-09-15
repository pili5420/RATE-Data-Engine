# RATE PRODUCTION ACCEPTANCE CRITERIA V1.0
Owner: RATE / OIS AI Control Center
Status: FROZEN

RATE_PRODUCTION_VALIDATION may be PASS only when every blocking gate below is PASS.

## Specification Gate
- RATE_PRODUCTION_LOGIC_SPEC V1.1 is the implemented reference.
- RATE_DATA_CONTRACT V1.0 is the implemented data contract.
- No uncontrolled strategy changes exist in code.

## Engineering Gate
- M7 implemented
- MHE implemented
- Stage implemented
- Rotation implemented
- Smart Money implemented
- Top50 implemented
- Short-Term Top30 implemented
- Long-Term Top30 implemented
- production lineage metadata present

## Data Quality Gate
- schema PASS
- type PASS
- range PASS
- freshness PASS
- duplicate PASS

## Logic Gate
- calculation PASS
- classification PASS
- cross-field consistency PASS
- missing-data behavior PASS

## Golden Test Gate
All required Golden Test Fixtures pass within defined tolerance.

## Ranking Gate
- candidate eligibility PASS
- Top50 ordering PASS
- Short Top30 ordering PASS
- Long Top30 ordering PASS
- tie-break PASS
- #50/#51 boundary PASS
- #30/#31 boundary PASS

## Deterministic Gate
Same spec + data contract + engine + input snapshot produces identical controlled outputs on rerun.

## E2E Gate
Production dry run succeeds from ingestion through final production JSON and validation.

## Evidence Gate
RATE_PRODUCTION_VALIDATION_EVIDENCE_V1 includes:
- spec version
- data contract version
- engine version
- git commit SHA
- input snapshot ID
- total/passed/failed tests
- golden test results
- validation results
- deterministic comparison
- E2E result
- blocking errors

## Final Acceptance
Only RATE / OIS AI Control Center may issue:
RATE_PRODUCTION_VALIDATION = PASS

Codex may produce evidence and machine-readable validation artifacts, but may not alter the frozen investment model to obtain PASS.
