from datetime import datetime, timezone
from typing import Dict, List

import requests
from flask import Flask, jsonify, render_template

app = Flask(__name__)

COINS: Dict[str, str] = {
    "bitcoin": "Bitcoin",
    "ethereum": "Ethereum",
}
API_URL = "https://api.coingecko.com/api/v3/simple/price"


def fetch_crypto_data() -> List[Dict[str, float]]:
    """Fetch price and 24h change for the configured coins."""
    try:
        response = requests.get(
            API_URL,
            params={
                "ids": ",".join(COINS.keys()),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
        response.raise_for_status()
        raw = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("No se pudieron obtener los precios") from exc

    rows: List[Dict[str, float]] = []
    for coin_id, display_name in COINS.items():
        coin_payload = raw.get(coin_id) or {}
        rows.append(
            {
                "id": coin_id,
                "name": display_name,
                "price": coin_payload.get("usd"),
                "change": coin_payload.get("usd_24h_change"),
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
