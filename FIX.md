# Mistakes and Fixes

## 1. Mock Firefly bridge is not used

**Mistake:**  
`MockFireflyDevice` is imported in `apps/firefly-bridge/src/index.ts`, but it is never instantiated. The `device` variable is only assigned when `FIREFLY_DEVICE_PATH` is provided. Without that environment variable, the bridge crashes on startup when `device.publicKeyHex()` is called.

**Fix:**  
Add a fallback branch that creates a mock device when no hardware path is configured.

```ts
if (DEVICE_PATH) {
  device = new SerialFireflyDevice(DEVICE_PATH);
} else {
  device = new MockFireflyDevice(/* seed/config */);
}
```

---

## 2. AES-256-GCM serial encryption is implemented but unused

**Mistake:**  
`crypto.ts` contains encryption, decryption, an anti-replay counter, and session-key handling, but nothing imports or uses it. `SerialFireflyDevice.sign()` still sends plaintext JSON over serial.

**Fix:**  
Wire `crypto.ts` into the serial signing flow so host-to-device messages are encrypted and protected against replay.

---

## 3. Firmware private key is stored in plaintext NVS

**Mistake:**  
`main.c` stores the generated private key using `nvs_set_blob`, without flash encryption, secure boot, eFuse protection, or a secure element. A physical flash dump could extract the signing key.

**Fix:**  
Move key storage to ESP32 flash encryption with secure boot enabled, or preferably use a dedicated secure element. Do not store the private key in plaintext NVS.

---

## 4. LP / peer capital pool logic is missing

**Mistake:**  
The pitch references LP first-loss pools, junior/senior tranches, and MPT share tokens, but the code only has a single operator-seeded first-loss pool configured through `INSURANCE_POOL_FIRST_LOSS_USD=250000`.

**Fix:**  
Implement LP accounting, tranche definitions, share issuance, capital contribution tracking, withdrawal logic, and loss allocation rules.

---

## 5. Pool state is in memory only

**Mistake:**  
Policies, reservations, pool balance, agent risk posteriors, premiums, and claims are stored in module-level Python dictionaries. They disappear when the API restarts.

**Fix:**  
Persist all pool and policy state in a durable database, preferably PostgreSQL, alongside the existing audit trail.

---

## 6. Pool settlement is disabled by default

**Mistake:**  
`insurance_use_vault=False`, so premiums and payouts are only accounting entries unless vault usage is explicitly enabled.

**Fix:**  
Either enable vault settlement by default for environments that claim on-chain settlement, or clearly document that vault settlement is optional and disabled in demo mode.

---

## 7. Sanctions and collusion lists are empty

**Mistake:**  
`_SANCTIONED_MERCHANTS` ships as an empty set. The AML model is deterministic and self-contained, so real sanctions screening is not happening.

**Fix:**  
Integrate a real sanctions / blockchain analytics provider such as Elliptic or Chainalysis, and populate sanctions and collusion lists from that provider.

---

## 8. `claim_policy.py` R8 cap does not affect payout

**Mistake:**  
Rule R8 caps loss locally to `per_claim_limit`, but `ClaimDecision` does not return the capped value. If the caller does not independently apply the cap, an over-limit claim may pay the full loss.

**Fix:**  
Add `capped_loss` or `payable_loss` to `ClaimDecision` and make downstream payout logic use that value.

---

## 9. README threshold does not match config

**Mistake:**  
The README says payments above `$10K` escalate, but `POLICY_THRESHOLD_USD` defaults to `$500`. The `$10K` value belongs to `INSURANCE_COVER_REQUIRED_ABOVE_USD`, which is a different gate.

**Fix:**  
Update the README to match the actual default config, or change the default config to match the README. Document both thresholds separately.

---

## 10. Duplicate dictionary keys in `insurance/tables.py`

**Mistake:**  
`LINE_PARAMS` defines `fx_slippage` twice and `mandate_breach` twice. Python silently keeps the last value.

**Fix:**  
Remove duplicate keys and keep a single authoritative definition for each insurance line.

---

## 11. Two overlapping insurance subsystems

**Mistake:**  
`insurance/` and `cover/` both define similar line parameters, pricing concepts, receipt hashing, and risk-loading logic. Their vocabulary overlaps, making it unclear which subsystem is authoritative.

**Fix:**  
Either merge them into one insurance engine or clearly separate and rename them, for example:

- `underwriting/` for PD-driven transaction pricing
- `cover/` for annual or parametric cover policies

---

## 12. Large binary assets are stored in git

**Mistake:**  
The repository contains about 9 MB of binary assets, including GIF and PNG diagram files. Some PNGs are redundant because SVG sources already exist.

**Fix:**  
Move large binaries to Git LFS or release assets. Keep source SVGs in the repository and regenerate PNGs when needed.

---

## 13. Branding is inconsistent

**Mistake:**  
The product is called Blaiko, but the SDK, route prefixes, and firmware namespace use `treasury` names such as `@treasury/insurance-sdk` and `/treasury/insurance`.

**Fix:**  
Standardize names across packages, routes, firmware namespaces, and documentation. Use a consistent scope such as `@blaiko/*` if Blaiko is the product brand.

---

## 14. Dead or unfinished code remains in the repo

**Mistake:**  
`crypto.ts` is unused, and `MockFireflyDevice` is imported but unused.

**Fix:**  
Either wire these modules into the working flow or remove them. Prefer wiring them in because they support important offline-demo and security claims.

---

## 15. Threshold and config values are scattered

**Mistake:**  
Important risk thresholds are spread across `config.py`, `tables.py`, `.env.example`, and several differently named variables.

**Fix:**  
Create one documented risk-appetite configuration surface that explains each threshold, default value, and environment override.

---

## 16. Insurance model is uncalibrated

**Mistake:**  
Priors, relative-risk multipliers, z-score slopes, and capital assumptions are reasonable guesses, but they are not calibrated against real loss data.

**Fix:**  
Collect real policy, claim, and loss data. Calibrate priors, multipliers, slopes, and capital loads against observed outcomes.

---

## 17. Insurance model assumes independent losses

**Mistake:**  
The pricing engine treats risks as mostly independent, but AI-agent failures can be highly correlated. A shared LLM regression, prompt-injection method, or oracle failure could trigger many simultaneous claims.

**Fix:**  
Add shared latent risk factors such as model provider, model version, tool provider, oracle dependency, or agent class. Add a catastrophe / correlation load and size capital against a ruin-probability target.

---

## 18. Hallucination risk is static

**Mistake:**  
The hallucination line uses a static annual rate, such as `cover_hallucination_rate = 0.03`, instead of being modelled per agent or per risk context.

**Fix:**  
Model hallucination risk using agent history, task category, model provider, model version, tool permissions, and observed claim history.

---

## 19. `capital_per_exposure=0.15` is arbitrary

**Mistake:**  
Capital is sized using a flat 15% exposure haircut rather than a tail-risk or ruin-probability model.

**Fix:**  
Replace the flat haircut with capital sizing based on loss distribution, correlation, target solvency level, and stress scenarios.

---

## 20. Hardware device lacks consumer-grade key security

**Mistake:**  
The hardware approval device cannot credibly support consumer self-custody if its key can be extracted from flash.

**Fix:**  
Use secure boot, flash encryption, anti-rollback protections, and preferably a secure element for private-key handling.

---

## 21. No device attestation

**Mistake:**  
The backend trusts a registered public key but does not verify that it belongs to a genuine hardware device rather than a software emulator.

**Fix:**  
Add manufacturer-signed device certificates and verify device attestation during registration and use.

---

## 22. Consumer hardware flow depends on USB serial

**Mistake:**  
The current Firefly flow is built around USB serial, which is not suitable for a consumer approval device.

**Fix:**  
Add BLE or NFC pairing with a mobile phone and design a consumer-grade onboarding flow.

---

## 23. No recovery flow for lost hardware

**Mistake:**  
A lost hardware device could lock the user out or require unsafe manual recovery.

**Fix:**  
Add social recovery, threshold recovery, backup keys, or XRPL multisign-based recovery.

---

## 24. KYA credentials have no expiry or revocation

**Mistake:**  
KYA credentials record `issued_on`, but there is no expiry field and no revocation registry.

**Fix:**  
Add credential expiration and a revocation registry. Verifiers must check both before accepting a credential.

---

## 25. Delegation chain is not cryptographically verifiable

**Mistake:**  
Orchestrator-to-sub-agent delegation is named, but the credential does not carry an attestable parent-child chain or enforce scope narrowing at issuance.

**Fix:**  
Add a signed delegation chain from principal to orchestrator to sub-agent. Enforce that child scopes are always a subset of parent scopes.

---

## 26. KYA trust depends on a single issuer wallet

**Mistake:**  
KYA scopes are asserted by one trusted issuer wallet. There is no issuer registry, issuer revocation, or selective-disclosure mechanism.

**Fix:**  
Add an issuer registry, issuer revocation, and support for hash commitments plus off-chain W3C VC or SD-JWT credentials for sensitive attributes.

---

## 27. KYA is not bound to hardware approval keys

**Mistake:**  
Agent identity is not linked to the controlling key or hardware approval key.

**Fix:**  
Allow KYA credentials to bind agent identity, controlling wallet, and Firefly hardware public key.

---

## 28. No published KYA schema or conformance suite

**Mistake:**  
There is a version byte, but no formal JSON schema, registry of agent types/scopes, extension policy, or test vectors.

**Fix:**  
Publish a KYA schema, versioning policy, extension rules, and cross-language conformance test vectors.

---

## 29. No dedicated KYA SDK

**Mistake:**  
There is an insurance SDK, but no dedicated KYA SDK.

**Fix:**  
Create `@blaiko/kya-sdk` with functions such as:

```ts
issueCredential()
verifyCredential(address, requiredScope)
parseIdentity()
buildDelegation(parent, childScopes)
revoke()
```

Also include an issuer-registry client and conformance tests.

---

## 30. Insurance capital is not routed by risk correlation

**Mistake:**  
All lines are effectively treated as if they belong in one operator pool, even though different lines have very different correlation profiles.

**Fix:**  
Route insurance lines to capital sources by risk type:

- `fx_slippage`: suitable for LP / DeFi pool capital
- `hallucination`: should stay on Blaiko balance sheet first, then rated reinsurer paper
- `mandate_breach`: should stay on Blaiko balance sheet first, then rated reinsurer paper

