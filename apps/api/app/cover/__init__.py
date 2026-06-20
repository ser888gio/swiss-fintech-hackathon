"""Cover module — annual agent insurance (hallucination + non-delivery).

A clean, self-contained module built on the pure actuarial core
(insurance/engine.py, insurance/risk.py, insurance/tables.py).
Premium is priced once per period (annual policy); the pool covers two perils:
  hallucination — agent sent wrong amount / wrong recipient (static rate)
  non_delivery  — merchant was paid but never delivered (PD-driven rate)
"""
