import glob
import re
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psutil
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
AXEOS_HOST = "192.168.100.117"
AXEOS_BASE_URL = f"http://{AXEOS_HOST}"
AXEOS_SYSTEM_INFO = f"{AXEOS_BASE_URL}/api/system/info"
DIFF_MULTIPLIERS: Dict[str, float] = {
    "": 1,
    "K": 1_000,
    "M": 1_000_000,
    "G": 1_000_000_000,
    "T": 1_000_000_000_000,
    "P": 1_000_000_000_000_000,
}
PI_TEMP_PATHS: List[Tuple[Path, float]] = [
    (Path("/sys/class/thermal/thermal_zone0/temp"), 1000),
    (Path("/sys/class/hwmon/hwmon0/temp1_input"), 1000),
]
PI_FAN_INPUT_GLOBS = [
    "/sys/devices/platform/*fan*/hwmon/hwmon*/fan1_input",
    "/sys/class/hwmon/hwmon*/fan1_input",
]
PI_FAN_PWM_GLOBS = [
    "/sys/devices/platform/*fan*/hwmon/hwmon*/pwm1",
    "/sys/class/hwmon/hwmon*/pwm1",
]


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: Optional[float], decimals: int = 2, suffix: str = "") -> Optional[str]:
    number = _safe_float(value)
    if number is None:
        return None
    return f"{number:,.{decimals}f}{suffix}"


def _format_duration(value: Optional[float]) -> Optional[str]:
    total_seconds = _safe_float(value)
    if total_seconds is None:
        return None
    seconds = int(total_seconds)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


SYSTEM_FIELDS = [
    ("hashRate", "Hashrate (GH/s)", lambda v: _format_number(v, 2, " GH/s")),
    ("power", "Potencia (W)", lambda v: _format_number(v, 2, " W")),
    ("temp", "Temp ASIC (°C)", lambda v: _format_number(v, 1, " °C")),
    ("vrTemp", "Temp VRM (°C)", lambda v: _format_number(v, 1, " °C")),
    ("fanspeed", "Velocidad ventilador", lambda v: _format_number(v, 0, " %")),
    ("fanrpm", "RPM ventilador", lambda v: _format_number(v, 0, " RPM")),
    ("sharesAccepted", "Shares aceptados", lambda v: _format_number(v, 0)),
    ("sharesRejected", "Shares rechazados", lambda v: _format_number(v, 0)),
    ("wifiRSSI", "Señal WiFi", lambda v: _format_number(v, 0, " dBm")),
    ("uptimeSeconds", "Uptime", _format_duration),
]


def fetch_dashboard_data():
    markets: List[Dict[str, float]] = []
    system: Optional[Dict[str, object]] = None
    pi_stats: Optional[Dict[str, object]] = None
    errors: List[str] = []

    try:
        markets = fetch_market_data()
    except RuntimeError as exc:
        errors.append(str(exc))

    try:
        system = _fetch_system_snapshot()
    except RuntimeError as exc:
        errors.append(str(exc))

    try:
        pi_stats = _fetch_pi_stats()
    except RuntimeError as exc:
        errors.append(str(exc))

    return {
        "markets": markets,
        "system": system,
        "pi": pi_stats,
        "error": "; ".join(errors) if errors else None,
    }


def fetch_market_data() -> List[Dict[str, float]]:
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


def _fetch_system_snapshot() -> Dict[str, object]:
    try:
        response = requests.get(AXEOS_SYSTEM_INFO, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("No se pudieron obtener los datos del AxeOS") from exc

    metrics = []
    for key, label, formatter in SYSTEM_FIELDS:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        formatted = formatter(value)
        if formatted is None:
            continue
        metrics.append({"id": key, "label": label, "value": formatted})

    highlight = _build_difficulty_highlight(payload)

    return {
        "meta": {
            "hostname": payload.get("hostname") or "AxeOS",
            "model": payload.get("ASICModel"),
            "ip": AXEOS_HOST,
        },
        "metrics": metrics,
        "highlight": highlight,
    }


def _parse_difficulty(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().upper()
    match = re.match(r"^([0-9]*\.?[0-9]+)\s*([KMGTP]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or ""
    multiplier = DIFF_MULTIPLIERS.get(unit, 1)
    return number * multiplier


def _format_difficulty_display(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    number = _safe_float(value)
    if number is None:
        return None
    units = ["", "K", "M", "G", "T", "P"]
    idx = 0
    while number >= 1000 and idx < len(units) - 1:
        number /= 1000
        idx += 1
    if units[idx]:
        return f"{number:.3g}{units[idx]}"
    return f"{number:,.0f}"


def _build_difficulty_highlight(payload: Dict[str, object]) -> Optional[Dict[str, str]]:
    candidates: List[Tuple[float, str, object]] = []
    mappings = [
        ("bestDiff", "Mejor share histórica"),
        ("bestSessionDiff", "Mejor share sesión"),
        ("stratumDiff", "Dificultad pool"),
    ]
    for key, label in mappings:
        raw = payload.get(key)
        parsed = _parse_difficulty(raw)
        if parsed is None:
            continue
        candidates.append((parsed, label, raw))

    if not candidates:
        return None

    best_value, source_label, raw_value = max(candidates, key=lambda item: item[0])
    display_value = _format_difficulty_display(raw_value) or _format_difficulty_display(best_value)
    if display_value is None:
        return None

    return {
        "label": f"Dificultad máxima ({source_label})",
        "value": display_value,
    }


def _fetch_pi_stats() -> Dict[str, object]:
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        virtual_mem = psutil.virtual_memory()
        disk_usage = psutil.disk_usage("/")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("No se pudieron obtener los datos del Raspberry Pi") from exc

    metrics: List[Dict[str, str]] = [
        {
            "id": "pi_cpu",
            "label": "Uso CPU",
            "value": f"{cpu_percent:.1f} %",
        },
        {
            "id": "pi_ram",
            "label": "RAM usada",
            "value": f"{_format_bytes(virtual_mem.used)} / {_format_bytes(virtual_mem.total)} "
            f"({virtual_mem.percent:.0f} %)",
        },
        {
            "id": "pi_disk",
            "label": "Disco raíz",
            "value": f"{_format_bytes(disk_usage.used)} / {_format_bytes(disk_usage.total)} "
            f"({disk_usage.percent:.0f} %)",
        },
    ]

    temperature = _get_pi_temperature()
    if temperature is not None:
        metrics.append(
            {
                "id": "pi_temp",
                "label": "Temperatura",
                "value": f"{temperature:.1f} °C",
            }
        )

    fan_speed = _get_pi_fan_speed()
    if fan_speed:
        metrics.append(
            {
                "id": "pi_fan",
                "label": "Ventilador",
                "value": fan_speed,
            }
        )

    highlight = None
    if temperature is not None:
        highlight = {
            "label": "Temperatura Raspberry Pi",
            "value": f"{temperature:.1f} °C",
        }

    return {
        "meta": {
            "hostname": socket.gethostname(),
        },
        "metrics": metrics,
        "highlight": highlight,
    }


def _get_pi_temperature() -> Optional[float]:
    for path, divisor in PI_TEMP_PATHS:
        try:
            if path.exists():
                raw = path.read_text().strip()
                if raw:
                    return float(raw) / divisor
        except (OSError, ValueError):
            continue

    try:
        output = subprocess.check_output(["vcgencmd", "measure_temp"], text=True).strip()
        match = re.search(r"temp=([0-9.]+)", output)
        if match:
            return float(match.group(1))
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        return None

    return None


def _get_pi_fan_speed() -> Optional[str]:
    for pattern in PI_FAN_INPUT_GLOBS:
        for path in glob.glob(pattern):
            try:
                value = Path(path).read_text().strip()
                if value:
                    rpm = float(value)
                    if rpm > 0:
                        return f"{rpm:,.0f} RPM"
            except (OSError, ValueError):
                continue

    for pattern in PI_FAN_PWM_GLOBS:
        for path in glob.glob(pattern):
            try:
                value = Path(path).read_text().strip()
                if not value:
                    continue
                duty = float(value)
                percent = duty / 255 * 100
                return f"{percent:.0f}% PWM"
            except (OSError, ValueError):
                continue

    return None


def _format_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024


@app.route("/")
def index():
    dashboard = fetch_dashboard_data()

    return render_template(
        "index.html",
        initial_data=dashboard["markets"],
        initial_system=dashboard["system"],
        initial_pi=dashboard["pi"],
        initial_error=dashboard["error"],
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/api/prices")
def prices():
    dashboard = fetch_dashboard_data()
    status_code = 200 if not dashboard["error"] else 207

    return jsonify(
        {
            "data": dashboard["markets"],
            "system": dashboard["system"],
            "pi": dashboard["pi"],
            "error": dashboard["error"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ), status_code


if __name__ == "__main__":
    app.run(use_reloader=True)
