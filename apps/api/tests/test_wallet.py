"""Unit tests for the read-only shared wallet normalization."""

from types import SimpleNamespace

import pytest

from app.tools import wallet


def test_transaction_normalizes_direction_amount_and_explorer() -> None:
    result = wallet._transaction(
        {
            "hash": "ABC123",
            "ledger_index": 42,
            "tx_json": {
                "Account": "rSender",
                "Destination": "rShared",
                "TransactionType": "Payment",
                "Amount": "1250000",
                "Fee": "12",
                "date": 0,
            },
            "meta": {"TransactionResult": "tesSUCCESS"},
        },
        "rShared",
        "devnet",
    )

    assert result.direction == "incoming"
    assert result.counterparty == "rSender"
    assert result.amount is not None
    assert result.amount.currency == "XRP"
    assert result.amount.value == "1.25"
    assert result.fee_xrp == "0.000012"
    assert result.explorer_url == "https://devnet.xrpl.org/transactions/ABC123"


def test_currency_label_decodes_xrpl_160_bit_code() -> None:
    assert wallet._currency_label("524C555344000000000000000000000000000000") == "RLUSD"


def test_connected_address_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wallet,
        "get_settings",
        lambda: SimpleNamespace(treasury_wallet_address="", treasury_wallet_seed=""),
    )
    with pytest.raises(ValueError, match="No shared treasury wallet"):
        wallet.connected_address()
