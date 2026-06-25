"""Receipt tool.

Produces a deterministic, hash-anchored audit receipt for every terminal payment
(settled / released / blocked). The canonical JSON is stable — same payment always
yields the same hash — so the hash can be anchored on-chain (XRPL memo) and
independently recomputed by an auditor.

ARS extension: the canonical hash now includes the guardrail_trail (if present on
the payment) and the current ARS audit log root hash, so the on-chain Memo anchors
the complete decision chain.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from ..schemas import Payment, Receipt
from . import audit_log as _audit_log


def build_receipt(payment: Payment) -> Receipt:
    return Receipt(
        payment_id=payment.id,
        intent=payment.intent,
        route_quote=payment.route_quote,
        compliance=payment.compliance,
        policy_decision=payment.policy_decision,
        status=payment.status,
        escrow_sequence=payment.escrow_sequence,
        escrow_create_tx_hash=payment.escrow_create_tx_hash,
        approval_signature=payment.approval_signature,
        tx_hash=payment.tx_hash,
        explorer_url=payment.explorer_url,
        audit_explanation=payment.audit_explanation,
        guardrail_trail=payment.guardrail_trail,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


def compute_receipt_hash(payment: Payment) -> str:
    """sha256 of the canonical JSON representation of the payment's decision trail."""
    return hashlib.sha256(_canonical_json(payment).encode()).hexdigest()


def compute_decision_hash(payment: Payment) -> str:
    """sha256 of the deterministic decision trail, known BEFORE submission.

    Covers only the inputs that authorized the payment — intent, route,
    compliance, policy, and the ARS guardrail trail + audit log root hash —
    and deliberately excludes post-execution fields (tx hash, status, timestamps).
    This makes it stable enough to anchor on the ledger as a transaction Memo at
    submission time, then recompute and match later against the persisted decision.

    ARS extension: guardrail_trail and audit_log_root are included so the Memo
    anchors the full constraint-engine decision chain.
    """
    guardrail_trail = getattr(payment, "guardrail_trail", None)
    data = {
        "paymentId": payment.id,
        "intent": {
            "from": payment.intent.from_account,
            "to": payment.intent.to,
            "senderName": payment.intent.sender_name,
            "senderCountry": payment.intent.sender_country,
            "receiverName": payment.intent.receiver_name,
            "receiverCountry": payment.intent.receiver_country,
            "receiverEntityType": payment.intent.receiver_entity_type.value,
            "purpose": payment.intent.purpose,
            "amount": f"{payment.intent.amount:.2f}",
            "currency": payment.intent.currency,
            "reference": payment.intent.reference,
        },
        "routeQuote": _route(payment),
        "compliance": _compliance(payment),
        "policyDecision": _policy(payment),
        "cover": _cover(payment),
        "guardrailTrail": _guardrail_trail(guardrail_trail),
        "auditLogRoot": _audit_log.root_hash(),
    }
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _canonical_json(payment: Payment) -> str:
    data = {
        "paymentId": payment.id,
        "status": payment.status.value,
        "intent": {
            "from": payment.intent.from_account,
            "to": payment.intent.to,
            "senderName": payment.intent.sender_name,
            "senderCountry": payment.intent.sender_country,
            "receiverName": payment.intent.receiver_name,
            "receiverCountry": payment.intent.receiver_country,
            "receiverEntityType": payment.intent.receiver_entity_type.value,
            "purpose": payment.intent.purpose,
            "amount": f"{payment.intent.amount:.2f}",
            "currency": payment.intent.currency,
            "reference": payment.intent.reference,
        },
        "routeQuote": _route(payment),
        "compliance": _compliance(payment),
        "policyDecision": _policy(payment),
        "cover": _cover(payment),
        "escrowSequence": payment.escrow_sequence,
        "approvalSignature": payment.approval_signature,
        "txHash": payment.tx_hash,
        "explorerUrl": payment.explorer_url,
        "auditExplanation": payment.audit_explanation,
        "guardrailTrail": _guardrail_trail(payment.guardrail_trail),
        "createdAt": _iso(payment.created_at),
        "updatedAt": _iso(payment.updated_at),
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _route(payment: Payment) -> dict | None:
    if payment.route_quote is None:
        return None
    r = payment.route_quote
    return {
        "destAmount": f"{r.dest_amount:.2f}",
        "estimatedFee": f"{r.estimated_fee:.2f}",
        "pathSummary": r.path_summary,
        "rate": f"{r.rate:.6f}",
        "sourceAmount": f"{r.source_amount:.2f}",
    }


def _compliance(payment: Payment) -> dict | None:
    if payment.compliance is None:
        return None
    c = payment.compliance
    return {
        "amlScore": c.aml_score,
        "explanation": c.explanation,
        "flags": c.flags,
        "geopoliticalRisk": _geopolitical_risk(c),
        "publicIntel": _public_intel(c),
        "sanctioned": c.sanctioned,
        "sanctionsMatches": [
            {
                "caption": match.caption,
                "datasets": match.datasets,
                "id": match.id,
                "schema": match.schema_,
                "score": f"{match.score:.6f}",
                "url": match.url,
            }
            for match in c.sanctions_matches
        ],
    }


def _geopolitical_risk(compliance) -> dict | None:
    if compliance.geopolitical_risk is None:
        return None
    g = compliance.geopolitical_risk
    return {
        "country": g.country,
        "riskLevel": g.risk_level,
        "score": g.score,
        "blocked": g.blocked,
        "requiresReview": g.requires_review,
        "reasons": g.reasons,
        "sources": g.sources,
        "summary": g.summary,
    }


def _public_intel(compliance) -> dict | None:
    if compliance.public_intel is None:
        return None
    intel = compliance.public_intel
    return {
        "confidence": intel.confidence,
        "flags": intel.flags,
        "score": intel.score,
        "sources": intel.sources,
        "summary": intel.summary,
    }


def _policy(payment: Payment) -> dict | None:
    if payment.policy_decision is None:
        return None
    d = payment.policy_decision
    return {
        "blocked": d.blocked,
        "blockReason": d.block_reason,
        "requiresApproval": d.requires_approval,
        "ruleFired": d.rule_fired,
        "reasons": d.reasons,
    }


def _cover(payment: Payment) -> dict | None:
    coverage = payment.coverage
    if coverage.quote is None:
        return None
    quote = coverage.quote
    return {
        "status": coverage.status.value,
        "requiredBy": coverage.required_by,
        "decision": quote.decision.value,
        "premium": quote.premium,
        "lines": quote.lines,
        "pd": quote.pd,
        "credibility": quote.credibility,
        "reason": coverage.reason or quote.reason,
        "receiptHash": quote.receipt_hash,
        "premiumTxHash": coverage.premium.tx_hash if coverage.premium else None,
        "premiumExplorerUrl": coverage.premium.explorer_url
        if coverage.premium
        else None,
    }


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _guardrail_trail(trail) -> list[dict] | None:
    if not trail:
        return None
    return [
        {
            "name": g.name,
            "passed": g.passed,
            "ruleFired": g.rule_fired,
            "reason": g.reason,
        }
        for g in trail
    ]
