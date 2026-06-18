"""Audit-report PDF renderer.

Read-only presentation layer over the canonical receipt: turns a terminal
payment's decision trail into a formatted PDF. It reuses `receipt.build_receipt`
so the PDF and the JSON receipt always describe the same facts — this module
never re-derives or re-decides anything.
"""

from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..schemas import Payment
from . import receipt as receipt_tool

_styles = getSampleStyleSheet()
_TITLE = ParagraphStyle("AuditTitle", parent=_styles["Title"], fontSize=18, spaceAfter=2)
_SUBTITLE = ParagraphStyle("AuditSubtitle", parent=_styles["Normal"], fontSize=9, textColor=colors.grey)
_SECTION = ParagraphStyle(
    "AuditSection", parent=_styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=4, textColor=colors.HexColor("#1f3b57")
)
_BODY = ParagraphStyle("AuditBody", parent=_styles["Normal"], fontSize=9.5, leading=13)
_MONO = ParagraphStyle("AuditMono", parent=_styles["Code"], fontSize=8, leading=10, wordWrap="CJK")


def build_receipt_pdf(payment: Payment) -> bytes:
    """Render the payment's audit trail to PDF bytes."""
    receipt = receipt_tool.build_receipt(payment)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Audit Report {payment.id}",
    )

    flow: list = [
        Paragraph("Treasury Payment — Audit Report", _TITLE),
        Paragraph(
            f"Payment {payment.id} &nbsp;·&nbsp; status: {receipt.status.value} &nbsp;·&nbsp; "
            f"generated {_iso(datetime.utcnow())}Z",
            _SUBTITLE,
        ),
        HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#1f3b57"), spaceBefore=6, spaceAfter=2),
    ]

    intent = receipt.intent
    flow += _section("Payment intent", [
        ("From", intent.from_account),
        ("To", intent.to),
        ("Sender", f"{intent.sender_name} ({intent.sender_country})"),
        ("Receiver", f"{intent.receiver_name} ({intent.receiver_country})"),
        ("Receiver type", intent.receiver_entity_type.value),
        ("Purpose", intent.purpose),
        ("Amount", f"{intent.amount:.2f} {intent.currency}"),
        ("Reference", intent.reference),
    ])

    route = receipt.route_quote
    if route is not None:
        flow += _section("Route", [
            ("Path", route.path_summary),
            ("Source amount", f"{route.source_amount:.2f}"),
            ("Destination amount", f"{route.dest_amount:.2f}"),
            ("Rate", f"{route.rate:.6f}"),
            ("Estimated fee", f"{route.estimated_fee:.2f}"),
        ])

    compliance = receipt.compliance
    if compliance is not None:
        rows = [
            ("Risk score", f"{compliance.aml_score}/100"),
            ("Sanctioned", "yes" if compliance.sanctioned else "no"),
            ("Flags", ", ".join(compliance.flags) or "none"),
            ("Explanation", compliance.explanation),
        ]
        if compliance.sanctions_matches:
            matches = "; ".join(
                f"{m.caption} ({m.score:.0%}, {', '.join(m.datasets) or 'n/a'})"
                for m in compliance.sanctions_matches
            )
            rows.append(("Sanctions matches", matches))
        if compliance.public_intel is not None:
            intel = compliance.public_intel
            rows.append(("Public intelligence", f"{intel.score}/100 — {intel.summary}"))
            if intel.sources:
                rows.append(("Intel sources", ", ".join(intel.sources)))
        flow += _section("Compliance", rows)

    policy = receipt.policy_decision
    if policy is not None:
        rows = [
            ("Outcome", _policy_outcome(policy)),
            ("Rule fired", policy.rule_fired or "none"),
            ("Requires approval", "yes" if policy.requires_approval else "no"),
        ]
        if policy.blocked and policy.block_reason:
            rows.append(("Block reason", policy.block_reason))
        if policy.reasons:
            rows.append(("Reasons", "; ".join(policy.reasons)))
        flow += _section("Policy decision", rows)

    settlement = [
        ("Escrow sequence", str(receipt.escrow_sequence) if receipt.escrow_sequence is not None else "—"),
        ("Approval signature", receipt.approval_signature or "—"),
        ("Transaction hash", receipt.tx_hash or "—"),
        ("Explorer", receipt.explorer_url or "—"),
        ("Created", _iso(receipt.created_at)),
        ("Updated", _iso(receipt.updated_at)),
    ]
    flow += _section("Settlement", settlement)

    if receipt.audit_explanation:
        flow.append(Paragraph("Narrative", _SECTION))
        flow.append(Paragraph(receipt.audit_explanation, _BODY))

    flow.append(Spacer(1, 10))
    flow.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=4))
    flow.append(Paragraph("Integrity", _SECTION))
    flow.append(Paragraph(
        "SHA-256 hash of the canonical decision trail. This document is a "
        "read-only render of data the backend computed; the hash can be "
        "independently recomputed from the receipt to detect any tampering.",
        _BODY,
    ))
    flow.append(Paragraph(payment.receipt_hash or "(not yet anchored)", _MONO))

    doc.build(flow)
    return buffer.getvalue()


def _section(title: str, rows: list[tuple[str, str]]) -> list:
    table = Table(
        [[Paragraph(f"<b>{label}</b>", _BODY), Paragraph(_escape(value), _BODY)] for label, value in rows],
        colWidths=[45 * mm, None],
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e0e0e0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [Paragraph(title, _SECTION), table]


def _policy_outcome(policy) -> str:
    if policy.blocked:
        return "refused"
    if policy.requires_approval:
        return "escalated for hardware approval"
    return "auto-settled"


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")
