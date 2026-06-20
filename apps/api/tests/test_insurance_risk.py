"""Statistical core — Beta posterior, credibility, experience-rating (spec §5/§6)."""

from app.insurance import risk
from app.insurance.risk import TxnFeatures
from app.insurance.tables import PD_MAX, PD_MIN


def test_from_band_seeds_prior_anchor():
    r = risk.from_band("ELITE", now=0.0)
    assert r.n0 == 80.0
    assert abs(r.alpha - 0.005 * 80.0) < 1e-9
    assert abs(r.beta - (1 - 0.005) * 80.0) < 1e-9
    # No observed mass yet → all weight on the prior.
    assert risk.credibility(r) == 0.0


def test_unknown_band_falls_back_to_standard():
    r = risk.from_band("NONSENSE", now=0.0)
    std = risk.from_band("STANDARD", now=0.0)
    assert r.n0 == std.n0 and r.a0 == std.a0


def test_credibility_rises_with_experience_and_stays_bounded():
    r = risk.from_band("STANDARD", now=0.0)
    z0 = risk.credibility(r)
    for _ in range(30):
        r = risk.update(r, defaulted=False, exposure_weight=1.0, now=0.0, tau_days=0)
    z1 = risk.credibility(r)
    assert z1 > z0
    assert 0.0 <= z1 <= 1.0


def test_default_raises_pd_and_success_lowers_it():
    r = risk.from_band("STANDARD", now=0.0)
    base = risk.pd_agent(r)
    after_default = risk.update(r, defaulted=True, exposure_weight=2.0, now=0.0, tau_days=0)
    after_success = risk.update(r, defaulted=False, exposure_weight=2.0, now=0.0, tau_days=0)
    assert risk.pd_agent(after_default) > base
    assert risk.pd_agent(after_success) < base


def test_exposure_weight_is_clamped():
    r = risk.from_band("STANDARD", now=0.0)
    huge = risk.update(r, defaulted=True, exposure_weight=100.0, now=0.0, tau_days=0)
    at_cap = risk.update(r, defaulted=True, exposure_weight=4.0, now=0.0, tau_days=0)
    assert risk.pd_agent(huge) == risk.pd_agent(at_cap)


def test_recency_decay_forgets_a_spike_toward_prior():
    r = risk.from_band("STANDARD", now=0.0)
    spiked = risk.update(r, defaulted=True, exposure_weight=4.0, now=0.0, tau_days=120)
    pd_spiked = risk.pd_agent(spiked)
    # Long quiet period + a tiny success: decay pulls the posterior back down.
    later = risk.update(spiked, defaulted=False, exposure_weight=0.25, now=120 * 86400.0 * 6, tau_days=120)
    assert risk.pd_agent(later) < pd_spiked


def test_pd_txn_clamped_within_bounds():
    r = risk.from_band("HIGH_RISK", now=0.0)
    hot = TxnFeatures(
        category="loan_repayment", tenor_band="gt_90d", cpty_band="unverified",
        first_seen=True, amount_z=5, velocity_z=5, concentration_z=5,
    )
    pd = risk.pd_txn(r, hot)
    assert PD_MIN <= pd <= PD_MAX


def test_relative_risk_moves_price_axis():
    r = risk.from_band("STANDARD", now=0.0)
    risky = risk.pd_txn(r, TxnFeatures(category="loan_repayment", tenor_band="gt_90d", cpty_band="unverified"))
    safe = risk.pd_txn(r, TxnFeatures(category="supplier_payment", tenor_band="instant", cpty_band="verified"))
    assert risky > safe
