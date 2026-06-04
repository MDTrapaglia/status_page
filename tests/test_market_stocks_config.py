from app import STOCKS


def test_stocks_include_sp500_and_exclude_ibm():
    symbols = [stock["symbol"] for stock in STOCKS]
    stock_by_symbol = {stock["symbol"]: stock for stock in STOCKS}

    assert "^GSPC" in symbols
    assert stock_by_symbol["^GSPC"]["name"] == "S&P 500"
    assert stock_by_symbol["^GSPC"]["tradingview"] == "SP:SPX"
    assert "IBM" not in symbols
