"""Unit tests for XRPL wire-format helpers."""

from app.xrpl_client import currency_code


def test_currency_code_encodes_rlusd_as_canonical_160_bit_hex() -> None:
    assert currency_code("RLUSD") == "524C555344000000000000000000000000000000"
    assert len(currency_code("RLUSD")) == 40


def test_currency_code_preserves_three_character_code() -> None:
    assert currency_code("USD") == "USD"
