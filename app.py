from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests
import yfinance as yf
from flask import Flask, jsonify, render_template

app = Flask(__name__)

COINS: List[Dict[str, str]] = [
    {"name": "Bitcoin", "symbol": "BTCUSDT"},
    {"name": "Ethereum", "symbol": "ETHUSDT"},
]
STOCKS: List[Dict[str, str]] = [
    {"name": "Marvell Technology (MRVL)", "symbol": "MRVL"},
]
BINANCE_URL = "https://api.binance.com/api/v3/ticker/24hr"


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_crypto_data() -> List[Dict[str, float]]:
    """Fetch price and 24h change for crypto and stocks."""
    crypto_data = _fetch_from_binance()
    stock_data = _fetch_from_yfinance()
    return crypto_data + stock_data


def _fetch_from_binance() -> List[Dict[str, float]]:
    symbols = [coin["symbol"] for coin in COINS]
    try:
        response = requests.get(
            BINANCE_URL,
            params={
                "symbols": "["
                + ",".join(f'"{symbol}"' for symbol in symbols)
                + "]",
            },
            timeout=10,
        )
        response.raise_for_status()
        raw = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("No se pudieron obtener los precios cripto") from exc

    payload_map = {item.get("symbol"): item for item in raw if isinstance(item, dict)}
    rows: List[Dict[str, float]] = []
    for coin in COINS:
        coin_payload = payload_map.get(coin["symbol"]) or {}
        rows.append(
            {
                "id": coin["symbol"],
                "name": coin["name"],
                "price": _safe_float(coin_payload.get("lastPrice")),
                "change": _safe_float(coin_payload.get("priceChangePercent")),
            }
        )
    return rows


def _fetch_from_yfinance() -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    try:
        for stock in STOCKS:
            ticker = yf.Ticker(stock["symbol"])
            history = ticker.history(period="2d", interval="1d")
            if history.empty or "Close" not in history:
                raise RuntimeError(f"No hay datos para {stock['symbol']}")

            closes = history["Close"]
            latest_price = closes.iloc[-1]
            change_pct: Optional[float] = None
            if len(closes) > 1:
                previous = closes.iloc[-2]
                if previous:
                    change_pct = ((latest_price - previous) / previous) * 100

            rows.append(
                {
                    "id": stock["symbol"],
                    "name": stock["name"],
                    "price": _safe_float(latest_price),
                    "change": _safe_float(change_pct),
                }
            )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("No se pudieron obtener los precios de acciones") from exc

    return rows


@app.route("/")
def index():
    try:
        crypto_data = fetch_crypto_data()
        error = None
    except RuntimeError as exc:
        crypto_data = []
        error = str(exc)

    return render_template(
        "index.html",
        initial_data=crypto_data,
        initial_error=error,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/api/prices")
def prices():
    try:
        crypto_data = fetch_crypto_data()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(
        {
            "data": crypto_data,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


if __name__ == "__main__":
    app.run(use_reloader=True)
