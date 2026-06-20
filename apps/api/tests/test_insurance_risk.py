from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.insurance import risk, tables
from app.schemas import TxnContext


def _ctx(**overrides) -> TxnContext:
    data = {
        "category": "supplier_payment",
        "tenorBand": "short",
        "cptyBand": "standard",
        "firstSeen": False,
        "amount": "500",
        "amountZ": 0.0,
        "velocityZ": 0.0,
        "concentrationZ": 0.0,
        "activeLines": ["merchant_default"],
    }
    data.update(overrides)
    return TxnContext(**data)


def test_from_band_initializes_prior():
    seeded = risk.from_band("ELITE", now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert seeded.score_band == "ELITE"
    assert seeded.alpha > 0
    assert seeded.beta > seeded.alpha


def test_credibility_starts_at_zero_for_all_prior():
    seeded = risk.from_band("STANDARD")
    assert risk.credibility(seeded) == 0.0


def test_credibility_rises_with_observations():
    seeded = risk.from_band("STANDARD")
    updated = risk.update(seeded, defaulted=False, exposure_weight=20.0)
    assert 0.0 < risk.credibility(updated) < 1.0


def test_update_decays_toward_prior_and_weights_defaults_higher():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    seeded = risk.from_band("HIGH", now=now - timedelta(days=60))
    risky = risk.update(seeded, defaulted=True, exposure_weight=5.0, now=now - timedelta(days=30))
    softened = risk.update(risky, defaulted=False, exposure_weight=1.0, now=now, tau_days=tables.TAU_DAYS)

    assert softened.alpha < risky.alpha
    assert softened.beta > seeded.beta


def test_pd_txn_clamps_to_bounds():
    seeded = risk.from_band("HIGH_RISK")
    pd = risk.pd_txn(
        seeded,
        _ctx(amountZ=10.0, velocityZ=10.0, concentrationZ=10.0, firstSeen=True, tenorBand="long", cptyBand="high"),
    )
    assert tables.PD_MIN <= pd <= tables.PD_MAX
    assert pd == tables.PD_MAX

