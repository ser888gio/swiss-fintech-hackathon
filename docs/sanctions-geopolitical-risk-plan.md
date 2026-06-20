# Sanctions and geopolitical risk plan

## Policy boundary

The LLM does not decide whether a destination is sanctioned or geopolitically
risky. It may explain the evidence after deterministic code has produced the
outcome. G2 remains a hard block and cannot be overridden by Firefly approval.
Geopolitical risk is a separate review signal: it raises the AML score and sends
the payment to G6/Firefly review.

## Implemented baseline

1. OpenSanctions continues to match a receiver as `Person` or `Company`, using
   name and country as matching properties.
2. `country_risk.py` evaluates the ISO country code against operator-owned,
   comma-separated block and review policies.
3. `ComplianceResult` records `sanctionsBasis` and a structured
   `geopoliticalRisk` result, so entity sanctions and territorial policy are
   distinguishable in the audit trail.
4. `SANCTIONS_BLOCKED_COUNTRIES` causes a G2 hard block. No transaction is
   constructed or signed.
5. `GEOPOLITICAL_REVIEW_COUNTRIES` applies the configured review score (65 by
   default), causing G6 hardware review under the default score threshold.
6. If a configured OpenSanctions call fails, the local demo list is still
   checked and the score is raised to the configured outage-review floor. The
   system therefore does not turn provider failure into a false clean result.

## Production rollout

1. Compliance/legal owns the country policy values and deploy approvals. Do not
   derive a country block from news sentiment.
2. Store policy bundles with version, effective time, source URLs, reviewer,
   checksum, and expiry. Persist the version used with every payment.
3. Add a scheduled ingestion job for authoritative jurisdiction sources chosen
   by legal (for example UN/EU/SECO/OFAC program data and FATF monitoring).
   Normalize these into a reviewed policy bundle; never let ingestion mutate
   active policy without approval.
4. Add a geopolitical evidence provider for conflict, instability, export
   controls, and corridor disruption. Its raw evidence may be gathered by an
   agent, but a deterministic mapping computes score, staleness, and policy
   effect. Missing or stale evidence must result in review, not auto-settlement.
5. Add database-backed screening evidence, cache TTLs, request correlation IDs,
   source timestamps, and replayable fixtures before claiming production-grade
   continuous monitoring.

## Verification matrix

| Scenario | Expected result |
|---|---|
| High-confidence person/company match | G2 block |
| Country in block policy | G2 block |
| Country in geopolitical review policy | G6/Firefly review |
| OpenSanctions unavailable | Review-score floor; audit fallback |
| Weak entity match, standard country | Continue through normal AML policy |
| LLM suggests ignoring risk | No effect on policy or signing |

The baseline is covered in `apps/api/tests/test_compliance.py`. Production
verification should additionally record provider request IDs, policy version,
decision trail, and (for allowed/reviewed payments) XRPL explorer evidence.
