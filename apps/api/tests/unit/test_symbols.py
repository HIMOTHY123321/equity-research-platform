import pytest

from app.schemas.symbols import InvalidTickerError, normalize_ticker


@pytest.mark.parametrize("raw", ["AAPL", "spy", "  qqq  ", "F", "BRK.A"])
def test_valid_tickers_are_normalized_uppercase(raw):
    normalized = normalize_ticker(raw)
    assert normalized == raw.strip().upper()


@pytest.mark.parametrize(
    "raw",
    ["", "TOOLONG", "123", "AA PL", "AAPL!", "aapl.", ".AAPL", "AA.PL.X"],
)
def test_invalid_tickers_are_rejected(raw):
    with pytest.raises(InvalidTickerError):
        normalize_ticker(raw)
