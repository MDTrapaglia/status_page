import json
from datetime import datetime, timezone
from typing import Dict, List

import requests
from flask import Flask, jsonify, render_template

app = Flask(__name__)

COINS: List[Dict[str, str]] = [
    {"name": "Bitcoin", "symbol": "BTCUSDT"},
    {"name": "Ethereum", "symbol": "ETHUSDT"},
]
BINANCE_URL = "https://api.binance.com/api/v3/ticker/24hr"


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_crypto_data() -> List[Dict[str, float]]:
    """Fetch price and 24h change directly from Binance."""
    symbols = [coin["symbol"] for coin in COINS]
    try:
        response = requests.get(
            BINANCE_URL,
            params={
                "symbols": json.dumps(symbols, separators=(",", ":")),
            },
            timeout=10,
        )
        response.raise_for_status()
        raw = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("No se pudieron obtener los precios") from exc

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
