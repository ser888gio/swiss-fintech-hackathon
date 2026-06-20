"""ARS Insurance (Pillar 3) — agent-default insurance pricing & risk engine.

A hybrid engine: a statistical core (Beta-posterior PD + relative-risk tables in
`risk.py`) wrapped in a deterministic, signed envelope (`price()` in `engine.py`).
The pure logic here has no I/O; the async settlement tool lives in
`app/tools/insurance.py` and reuses the existing vault/execution/audit layers.

See docs/insurance-pricing-risk-engine.md for the full design.
"""
