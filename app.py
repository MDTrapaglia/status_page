import glob
import json
import logging
import re
import random
import socket
import subprocess
import threading
import time
import math
from collections import deque
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
import pandas as pd
import psutil
import requests
import yfinance as yf
from flask import Flask, abort, jsonify, render_template, request, send_file
from zoneinfo import ZoneInfo

app = Flask(__name__)
LOG_PATH = Path("status_page.log")
AUTH_TOKEN = "gaelito2025"
PORT_BLOCK_ROOT = Path("/home/mtrapaglia/projects/port_block")
PORT_BLOCK_PLOTS = PORT_BLOCK_ROOT / "ufw_plots"
PORT_BLOCK_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg"}
PORT_BLOCK_EXCLUDED_PLOTS = {"ufw_top_ips"}
CONNECTIVITY_TEST_TARGETS = [("1.1.1.1", 53), ("8.8.8.8", 53)]
CONNECTIVITY_TEST_TIMEOUT = 2.0


def _configure_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [logging.StreamHandler()]
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                LOG_PATH,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        )
    except OSError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=handlers,
        force=True,
    )


_configure_logging()
logger = logging.getLogger("status_page")
logger.info("Logging initialized; writing to %s", LOG_PATH)

COINS: List[Dict[str, str]] = [
    {"name": "Bitcoin", "symbol": "BTCUSDT", "yf_symbol": "BTC-USD"},
    {"name": "Ethereum", "symbol": "ETHUSDT", "yf_symbol": "ETH-USD"},
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
MAX_FAN_RPM = 6000.0
PI_HISTORY_WINDOW = timedelta(hours=4)
PI_HISTORY: Deque[Dict[str, object]] = deque()
PI_HISTORY_LOCK = threading.Lock()
PI_SAMPLE_INTERVAL_SECONDS = 60
PI_FULL_HISTORY_PATH = Path("pi_history_full.jsonl")
PI_FULL_HISTORY_RETENTION = timedelta(days=30)
PI_FULL_HISTORY_MAX_API_POINTS = 2000
PI_FULL_HISTORY: List[Dict[str, object]] = []
SESSION_STATE_PATH = Path("session_state.json")
QUOTES_PATH = Path("acim_quotes.json")
QUOTES_MAX_AGE = timedelta(days=7)
QUOTE_SOURCES = [
    {"url": "https://coachingdelser.com/frases-un-curso-de-milagros/", "selector": "blockquote, p"},
    {"url": "https://www.enbuenasmanos.com/frases-del-libro-un-curso-de-milagros", "selector": "blockquote, li"},
]
FALLBACK_QUOTES = [
    "Nada real puede ser amenazado. Nada irreal existe. En esto radica la paz de Dios.",
    "El amor no guarda rencores, y cada experiencia es una oportunidad de aprender a amar sin condiciones.",
    "Estoy decidido a ver las cosas de otra manera.",
    "Soy tal como Dios me creó. La luz, la alegría y la paz moran en mí.",
    "No hay nada que temer, porque el amor perfecto expulsa todo temor.",
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


def _check_internet_connectivity() -> bool:
    for host, port in CONNECTIVITY_TEST_TARGETS:
        try:
            with socket.create_connection((host, port), CONNECTIVITY_TEST_TIMEOUT):
                return True
        except OSError:
            continue
    return False


def _load_cached_quotes() -> List[str]:
    if not QUOTES_PATH.exists():
        return []
    try:
        with QUOTES_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Could not read cached quotes: %s", exc)
    return []


def _save_cached_quotes(quotes: List[str]) -> None:
    try:
        with QUOTES_PATH.open("w", encoding="utf-8") as handle:
            json.dump(quotes, handle, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning("Could not save quotes to disk: %s", exc)


def _scrape_quotes() -> List[str]:
    scraped: List[str] = []
    headers = {"User-Agent": "status-page/1.0 (+https://example.local)"}
    for source in QUOTE_SOURCES:
        url = source["url"]
        selector = source.get("selector") or "blockquote"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            candidates = soup.select(selector) or soup.find_all("blockquote")
            for tag in candidates:
                text = " ".join(tag.get_text(separator=" ").split())
                if not text:
                    continue
                if len(text) < 40 or len(text) > 320:
                    continue
                scraped.append(text)
        except requests.RequestException as exc:
            logger.warning("Could not scrape %s: %s", url, exc)
            continue
    unique = []
    seen = set()
    for item in scraped:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _ensure_quotes() -> List[str]:
    quotes = _load_cached_quotes()
    is_stale = False
    try:
        if QUOTES_PATH.exists():
            mtime = datetime.fromtimestamp(QUOTES_PATH.stat().st_mtime, tz=timezone.utc)
            is_stale = datetime.now(timezone.utc) - mtime > QUOTES_MAX_AGE
    except OSError:
        is_stale = True

    if not quotes or is_stale:
        fresh = _scrape_quotes()
        if fresh:
            quotes = fresh
            _save_cached_quotes(fresh)

    if not quotes:
        quotes = FALLBACK_QUOTES

    return quotes


def _get_daily_quote() -> Optional[str]:
    quotes = _ensure_quotes()
    if not quotes:
        return None
    try:
        tz = ZoneInfo("America/Argentina/Buenos_Aires")
    except Exception:
        tz = timezone(timedelta(hours=-3))
    today_key = datetime.now(tz=tz).strftime("%Y%m%d")
    rnd = random.Random(today_key)
    return rnd.choice(quotes)


def _calculate_change_from_series(closes: "pd.Series", days: int) -> Optional[float]:
    """Return percentage change using the last price vs. closest price at least `days` ago."""
    if closes is None or closes.empty:
        return None
    latest = closes.iloc[-1]
    if pd.isna(latest):
        return None

    cutoff = closes.index[-1] - timedelta(days=days)
    historical = closes[closes.index <= cutoff]
    if historical.empty:
        return None
    previous = historical.iloc[-1]
    if previous in (0, None) or pd.isna(previous):
        return None

    try:
        return ((float(latest) - float(previous)) / float(previous)) * 100
    except ZeroDivisionError:
        return None


def _fetch_yfinance_snapshot(symbol: str) -> Dict[str, Optional[float]]:
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="2mo", interval="1d")
        if history.empty or "Close" not in history:
            raise RuntimeError(f"No data for {symbol}")

        closes = history["Close"].dropna()
        if closes.empty:
            raise RuntimeError(f"No data for {symbol}")

        latest_price = closes.iloc[-1]
        change_1d = _calculate_change_from_series(closes, 1)
        change_7d = _calculate_change_from_series(closes, 7)
        change_30d = _calculate_change_from_series(closes, 30)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"No data for {symbol}") from exc

    return {
        "price": _safe_float(latest_price),
        "change_1d": _safe_float(change_1d),
        "change_7d": _safe_float(change_7d),
        "change_30d": _safe_float(change_30d),
    }


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


SYSTEM_FIELDS = [
    ("hashRate", "Hashrate (GH/s)", lambda v: _format_number(v, 2, " GH/s")),
    ("power", "Power (W)", lambda v: _format_number(v, 2, " W")),
    ("temp", "ASIC temp (°C)", lambda v: _format_number(v, 1, " °C")),
    ("vrTemp", "VRM temp (°C)", lambda v: _format_number(v, 1, " °C")),
    ("fanspeed", "Fan speed", lambda v: _format_number(v, 0, " %")),
    ("fanrpm", "Fan RPM", lambda v: _format_number(v, 0, " RPM")),
    ("sharesAccepted", "Accepted shares", lambda v: _format_number(v, 0)),
    ("sharesRejected", "Rejected shares", lambda v: _format_number(v, 0)),
    ("wifiRSSI", "WiFi signal", lambda v: _format_number(v, 0, " dBm")),
    ("uptimeSeconds", "Uptime", _format_duration),
    ("bestSessionDiff", "Best session (Diff)", _format_difficulty_display),
]


def _calculate_energy_efficiency(payload: Dict[str, object]) -> Optional[float]:
    power_watts = _safe_float(payload.get("power"))
    hash_rate_gh = _safe_float(payload.get("hashRate"))
    if power_watts is None or hash_rate_gh is None or hash_rate_gh <= 0:
        return None
    hash_rate_th = hash_rate_gh / 1000
    if hash_rate_th <= 0:
        return None
    return power_watts / hash_rate_th


def _load_port_block_payload() -> Dict[str, object]:
    plots: List[Dict[str, object]] = []
    errors: List[str] = []
    latest_plot_time: Optional[datetime] = None

    try:
        for path in sorted(PORT_BLOCK_PLOTS.glob("*")):
            if path.suffix.lower() not in PORT_BLOCK_ALLOWED_SUFFIXES:
                continue
            if path.stem in PORT_BLOCK_EXCLUDED_PLOTS:
                continue
            try:
                mtime_dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                mtime = mtime_dt.isoformat()
                if latest_plot_time is None or mtime_dt > latest_plot_time:
                    latest_plot_time = mtime_dt
            except OSError:
                mtime = None
            plots.append(
                {
                    "filename": str(path.relative_to(PORT_BLOCK_ROOT)),
                    "label": path.stem.replace("_", " ").title(),
                    "updated_at": mtime,
                    "url": f"/port-block/{path.relative_to(PORT_BLOCK_ROOT)}",
                }
            )
    except OSError as exc:
        errors.append(f"Could not read plots: {exc}")

    return {
        "plots": plots,
        "updated_at": latest_plot_time.isoformat() if latest_plot_time else None,
        "error": "; ".join(errors) if errors else None,
    }


def fetch_dashboard_data(include_port_block: bool = True):
    markets: List[Dict[str, float]] = []
    system: Optional[Dict[str, object]] = None
    pi_stats: Optional[Dict[str, object]] = None
    pi_raw: Optional[Dict[str, object]] = None
    errors: List[str] = []
    port_block: Optional[Dict[str, object]] = None

    try:
        markets = fetch_market_data()
    except RuntimeError as exc:
        errors.append(str(exc))

    try:
        system = _fetch_system_snapshot()
    except RuntimeError as exc:
        errors.append(str(exc))

    try:
        with PI_HISTORY_LOCK:
            should_seed = not PI_HISTORY
        pi_stats, pi_raw = _fetch_pi_stats(check_connectivity=should_seed)
        if should_seed:
            _record_pi_history(pi_raw)
    except RuntimeError as exc:
        errors.append(str(exc))

    if include_port_block:
        port_block = _load_port_block_payload()
        if port_block.get("error"):
            errors.append(str(port_block["error"]))

    if errors:
        logger.warning("Dashboard generated with errors: %s", "; ".join(errors))

    quote = _get_daily_quote()

    return {
        "markets": markets,
        "system": system,
        "pi": pi_stats,
        "pi_history": _build_pi_history_series(),
        "pi_history_full": _build_pi_full_history_series(),
        "quote": {"text": quote} if quote else None,
        "port_block": port_block if include_port_block else None,
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
        logger.warning("Could not fetch crypto prices from Binance: %s", exc)
        raise RuntimeError("Could not fetch crypto prices") from exc

    payload_map = {item.get("symbol"): item for item in raw if isinstance(item, dict)}
    rows: List[Dict[str, float]] = []
    for coin in COINS:
        coin_payload = payload_map.get(coin["symbol"]) or {}
        change_1d = _safe_float(coin_payload.get("priceChangePercent"))
        price = _safe_float(coin_payload.get("lastPrice"))
        change_7d: Optional[float] = None
        change_30d: Optional[float] = None

        yf_symbol = coin.get("yf_symbol")
        if yf_symbol:
            try:
                snapshot = _fetch_yfinance_snapshot(yf_symbol)
                change_1d = snapshot.get("change_1d") if snapshot.get("change_1d") is not None else change_1d
                change_7d = snapshot.get("change_7d")
                change_30d = snapshot.get("change_30d")
                if snapshot.get("price") is not None:
                    price = snapshot["price"]
            except RuntimeError as exc:
                logger.warning("Could not fetch weekly/monthly data for %s: %s", yf_symbol, exc)

        rows.append(
            {
                "id": coin["symbol"],
                "name": coin["name"],
                "price": price,
                "change": change_1d,
                "change_7d": change_7d,
                "change_30d": change_30d,
            }
        )
    return rows


def _fetch_from_yfinance() -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    try:
        for stock in STOCKS:
            snapshot = _fetch_yfinance_snapshot(stock["symbol"])

            rows.append(
                {
                    "id": stock["symbol"],
                    "name": stock["name"],
                    "price": snapshot.get("price"),
                    "change": snapshot.get("change_1d"),
                    "change_7d": snapshot.get("change_7d"),
                    "change_30d": snapshot.get("change_30d"),
                }
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch stock prices: %s", exc)
        raise RuntimeError("Could not fetch stock prices") from exc

    return rows


def _fetch_system_snapshot() -> Dict[str, object]:
    try:
        response = requests.get(AXEOS_SYSTEM_INFO, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("Could not fetch AxeOS data (%s): %s", AXEOS_SYSTEM_INFO, exc)
        raise RuntimeError("Could not fetch AxeOS data") from exc

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

    session_info = _update_session_tracking(payload.get("uptimeSeconds"))
    if session_info:
        metrics.append(
            {
                "id": "session_duration",
                "label": "Session duration",
                "value": _format_duration(session_info["current_seconds"]) or "—",
            }
        )
        metrics.append(
            {
                "id": "session_total",
                "label": "Total session time",
                "value": _format_duration(session_info["total_seconds"]) or "—",
            }
        )

    efficiency = _calculate_energy_efficiency(payload)
    if efficiency is not None:
        metrics.append(
            {
                "id": "energy_efficiency",
                "label": "Efficiency (J/TH)",
                "value": f"{efficiency:.2f}",
            }
        )

    highlight = _build_difficulty_highlight(payload)
    session_highlight = _build_session_highlight(payload)

    return {
        "meta": {
            "hostname": payload.get("hostname") or "AxeOS",
            "model": payload.get("ASICModel"),
            "ip": AXEOS_HOST,
        },
        "metrics": metrics,
        "highlight": highlight,
        "session_highlight": session_highlight,
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


def _build_difficulty_highlight(payload: Dict[str, object]) -> Optional[Dict[str, str]]:
    best_raw = payload.get("bestDiff")
    best_value = _parse_difficulty(best_raw)
    if best_value is not None:
        display_value = _format_difficulty_display(best_raw) or _format_difficulty_display(best_value)
        if display_value is not None:
            return {
                "label": "Highest difficulty (all time)",
                "value": display_value,
            }

    candidates: List[Tuple[float, str, object]] = []
    mappings = [
        ("bestSessionDiff", "best session share"),
        ("stratumDiff", "pool difficulty"),
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
    fallback_display = _format_difficulty_display(raw_value) or _format_difficulty_display(best_value)
    if fallback_display is None:
        return None

    return {
        "label": f"Highest difficulty ({source_label})",
        "value": fallback_display,
    }


def _build_session_highlight(payload: Dict[str, object]) -> Optional[Dict[str, str]]:
    session_raw = payload.get("bestSessionDiff")
    session_value = _parse_difficulty(session_raw)
    if session_value is None:
        return None

    display_value = _format_difficulty_display(session_raw) or _format_difficulty_display(session_value)
    if display_value is None:
        return None

    return {
        "label": "Best share of the session",
        "value": display_value,
    }


def _load_pi_full_history_from_disk() -> None:
    if not PI_FULL_HISTORY_PATH.exists():
        return

    entries: List[Dict[str, object]] = []
    retention_cutoff = datetime.now(timezone.utc) - PI_FULL_HISTORY_RETENTION if PI_FULL_HISTORY_RETENTION else None
    pruned_on_load = 0
    try:
        with PI_FULL_HISTORY_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw_line = line.strip()
                if not raw_line:
                    continue
                try:
                    payload = json.loads(raw_line)
                    if not isinstance(payload, dict):
                        continue
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue

                ts_raw = payload.get("ts")
                if not ts_raw:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_raw)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    continue

                if retention_cutoff and ts < retention_cutoff:
                    pruned_on_load += 1
                    continue

                online_raw = payload.get("online")
                online: Optional[bool]
                if isinstance(online_raw, bool):
                    online = online_raw
                elif online_raw in (0, 1):
                    online = bool(online_raw)
                else:
                    online = None

                entries.append(
                    {
                        "ts": ts,
                        "cpu": _safe_float(payload.get("cpu")),
                        "ram": _safe_float(payload.get("ram")),
                        "temperature": _safe_float(payload.get("temperature")),
                        "fan": _safe_float(payload.get("fan")),
                        "online": online,
                    }
                )
    except OSError as exc:
        logger.warning("Could not load full Pi history: %s", exc)
        return

    cutoff = datetime.now(timezone.utc) - PI_HISTORY_WINDOW
    snapshot: Optional[List[Dict[str, object]]] = None
    with PI_HISTORY_LOCK:
        PI_FULL_HISTORY.clear()
        PI_HISTORY.clear()
        for entry in entries:
            PI_FULL_HISTORY.append(entry)
            if entry["ts"] and entry["ts"] >= cutoff:
                PI_HISTORY.append(entry)
        if pruned_on_load:
            snapshot = list(PI_FULL_HISTORY)
    if snapshot is not None:
        _rewrite_pi_full_history_file(snapshot)
        logger.info("Pruned full Pi history on startup; discarded points: %s", pruned_on_load)


def _persist_pi_full_history_entry(entry: Dict[str, object]) -> None:
    payload = {
        "ts": entry.get("ts").isoformat() if isinstance(entry.get("ts"), datetime) else entry.get("ts"),
        "cpu": entry.get("cpu"),
        "ram": entry.get("ram"),
        "temperature": entry.get("temperature"),
        "fan": entry.get("fan"),
        "online": entry.get("online"),
    }
    try:
        with PI_FULL_HISTORY_PATH.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
    except OSError as exc:
        logger.warning("Could not save full Pi history: %s", exc)


def _serialize_pi_entry(entry: Dict[str, object]) -> Dict[str, object]:
    ts = entry.get("ts")
    return {
        "ts": ts.isoformat() if isinstance(ts, datetime) else ts,
        "cpu": entry.get("cpu"),
        "ram": entry.get("ram"),
        "temperature": entry.get("temperature"),
        "fan": entry.get("fan"),
        "online": entry.get("online"),
    }


def _rewrite_pi_full_history_file(entries) -> None:
    try:
        with PI_FULL_HISTORY_PATH.open("w", encoding="utf-8") as handle:
            for entry in entries:
                json.dump(_serialize_pi_entry(entry), handle, ensure_ascii=False)
                handle.write("\n")
    except OSError as exc:
        logger.warning("Could not compact full Pi history: %s", exc)


def _build_pi_history_payload(entries) -> Dict[str, List[Optional[float]]]:
    labels: List[str] = []
    temperature: List[Optional[float]] = []
    cpu: List[Optional[float]] = []
    ram: List[Optional[float]] = []
    fan: List[Optional[float]] = []
    online: List[Optional[bool]] = []

    for entry in entries:
        ts = entry.get("ts")
        if not ts:
            continue
        labels.append(ts.isoformat() if isinstance(ts, datetime) else str(ts))
        temperature.append(entry.get("temperature"))
        cpu.append(entry.get("cpu"))
        ram.append(entry.get("ram"))
        fan.append(entry.get("fan"))
        online.append(entry.get("online"))

    return {
        "labels": labels,
        "temperature": temperature,
        "cpu": cpu,
        "ram": ram,
        "fan": fan,
        "online": online,
    }


def _record_pi_history(point: Optional[Dict[str, object]]):
    if not point:
        return
    now = datetime.now(timezone.utc)
    entry = {"ts": now, **point}
    removed_full = 0
    pruned_snapshot: Optional[List[Dict[str, object]]] = None
    with PI_HISTORY_LOCK:
        PI_HISTORY.append(entry)
        cutoff = now - PI_HISTORY_WINDOW
        while PI_HISTORY and PI_HISTORY[0]["ts"] < cutoff:
            PI_HISTORY.popleft()
        PI_FULL_HISTORY.append(entry)
        if PI_FULL_HISTORY_RETENTION:
            retention_cutoff = now - PI_FULL_HISTORY_RETENTION
            while PI_FULL_HISTORY and PI_FULL_HISTORY[0]["ts"] < retention_cutoff:
                PI_FULL_HISTORY.pop(0)
                removed_full += 1
            if removed_full:
                pruned_snapshot = list(PI_FULL_HISTORY)
    _persist_pi_full_history_entry(entry)
    if pruned_snapshot is not None:
        _rewrite_pi_full_history_file(pruned_snapshot)
        logger.info("Compacted full Pi history; old points discarded: %s", removed_full)


def _build_pi_history_series() -> Dict[str, List[Optional[float]]]:
    with PI_HISTORY_LOCK:
        return _build_pi_history_payload(PI_HISTORY)


def _downsample_entries(entries: List[Dict[str, object]], max_points: int) -> List[Dict[str, object]]:
    if max_points <= 0 or len(entries) <= max_points:
        return list(entries)
    step = max(1, math.ceil(len(entries) / max_points))
    sampled = entries[::step]
    if sampled and sampled[-1] is not entries[-1]:
        sampled.append(entries[-1])
    return sampled


def _build_pi_full_history_series() -> Dict[str, List[Optional[float]]]:
    with PI_HISTORY_LOCK:
        entries = list(PI_FULL_HISTORY)
    downsampled = _downsample_entries(entries, PI_FULL_HISTORY_MAX_API_POINTS)
    return _build_pi_history_payload(downsampled)


def _load_session_state() -> Dict[str, float]:
    if not SESSION_STATE_PATH.exists():
        return {"total_completed_seconds": 0.0, "last_uptime": 0.0}
    try:
        with SESSION_STATE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            return {
                "total_completed_seconds": float(data.get("total_completed_seconds", 0.0)),
                "last_uptime": float(data.get("last_uptime", 0.0)),
            }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"total_completed_seconds": 0.0, "last_uptime": 0.0}


def _save_session_state(state: Dict[str, float]) -> None:
    try:
        with SESSION_STATE_PATH.open("w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except OSError:
        pass


def _update_session_tracking(uptime_value) -> Optional[Dict[str, float]]:
    uptime_seconds = _safe_float(uptime_value)
    if uptime_seconds is None:
        return None

    state = _load_session_state()
    total_completed = state.get("total_completed_seconds", 0.0)
    last_uptime = state.get("last_uptime", 0.0)

    if uptime_seconds < last_uptime:
        total_completed += last_uptime

    state["last_uptime"] = uptime_seconds
    state["total_completed_seconds"] = total_completed
    _save_session_state(state)

    return {
        "current_seconds": uptime_seconds,
        "total_seconds": total_completed + uptime_seconds,
    }


def _fetch_pi_stats(check_connectivity: bool = False) -> Tuple[Dict[str, object], Dict[str, Optional[float]]]:
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        virtual_mem = psutil.virtual_memory()
        disk_usage = psutil.disk_usage("/")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read Raspberry Pi stats: %s", exc)
        raise RuntimeError("Could not read Raspberry Pi stats") from exc

    online_status: Optional[bool] = None
    if check_connectivity:
        try:
            online_status = _check_internet_connectivity()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Connectivity check failed: %s", exc)

    metrics: List[Dict[str, str]] = [
        {
            "id": "pi_cpu",
            "label": "CPU usage",
            "value": f"{cpu_percent:.1f} %",
        },
        {
            "id": "pi_ram",
            "label": "RAM used",
            "value": f"{_format_bytes(virtual_mem.used)} / {_format_bytes(virtual_mem.total)} "
            f"({virtual_mem.percent:.0f} %)",
        },
        {
            "id": "pi_disk",
            "label": "Root disk",
            "value": f"{_format_bytes(disk_usage.used)} / {_format_bytes(disk_usage.total)} "
            f"({disk_usage.percent:.0f} %)",
        },
    ]

    ssd_path = Path("/mnt/ssd")
    if ssd_path.exists():
        try:
            ssd_usage = psutil.disk_usage(str(ssd_path))
            metrics.append(
                {
                    "id": "pi_ssd",
                    "label": "SSD /mnt/ssd",
                    "value": f"{_format_bytes(ssd_usage.used)} / {_format_bytes(ssd_usage.total)} "
                    f"({ssd_usage.percent:.0f} %)",
                }
            )
        except OSError:
            pass

    temperature = _get_pi_temperature()
    if temperature is not None:
        metrics.append(
            {
                "id": "pi_temp",
                "label": "Temperature",
                "value": f"{temperature:.1f} °C",
            }
        )

    fan_display, fan_percent = _get_pi_fan_speed()
    if fan_display:
        metrics.append(
            {
                "id": "pi_fan",
                "label": "Fan",
                "value": fan_display,
            }
        )

    highlight = None
    if temperature is not None:
        highlight = {
            "label": "Raspberry Pi temperature",
            "value": f"{temperature:.1f} °C",
        }

    display = {
        "meta": {
            "hostname": socket.gethostname(),
        },
        "metrics": metrics,
        "highlight": highlight,
    }

    raw_point = {
        "cpu": cpu_percent,
        "ram": virtual_mem.percent,
        "temperature": temperature,
        "fan": fan_percent,
        "online": online_status,
    }

    return display, raw_point


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


def _get_pi_fan_speed() -> Tuple[Optional[str], Optional[float]]:
    for pattern in PI_FAN_INPUT_GLOBS:
        for path in glob.glob(pattern):
            try:
                value = Path(path).read_text().strip()
                if value:
                    rpm = float(value)
                    if rpm > 0:
                        percent = min(100.0, (rpm / MAX_FAN_RPM) * 100)
                        return f"{rpm:,.0f} RPM", percent
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
                return f"{percent:.0f}% PWM", percent
            except (OSError, ValueError):
                continue

    return None, None


def _format_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024


def _pi_sampler_loop():
    while True:
        try:
            _, raw_point = _fetch_pi_stats(check_connectivity=True)
            _record_pi_history(raw_point)
        except RuntimeError as exc:
            logger.warning("Error during periodic Pi sampling: %s", exc)
        time.sleep(PI_SAMPLE_INTERVAL_SECONDS)


def _start_pi_sampler():
    thread = threading.Thread(target=_pi_sampler_loop, name="pi-sampler", daemon=True)
    thread.start()
    logger.info("Raspberry Pi sampling thread started")


_load_pi_full_history_from_disk()
_start_pi_sampler()


@app.before_request
def _require_token():
    if request.endpoint == "static":
        return None
    if request.endpoint == "port_block_asset":
        token = request.args.get("token")
        if token == AUTH_TOKEN:
            return None
        return "Resource not available", 404
    token = request.args.get("token")
    if token == AUTH_TOKEN:
        return None

    logger.warning(
        "Access denied to %s from %s: missing or invalid token",
        request.path,
        request.remote_addr or "unknown",
    )
    return "Resource not available", 404


@app.route("/port-block/<path:filename>")
def port_block_asset(filename):
    target = (PORT_BLOCK_ROOT / filename).resolve()
    root = PORT_BLOCK_ROOT.resolve()
    if root not in target.parents and target != root:
        abort(404)
    if not target.exists() or not target.is_file():
        abort(404)
    try:
        response = send_file(target)
    except OSError:
        abort(404)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    logger.info("Rendering main page")
    dashboard = fetch_dashboard_data()

    return render_template(
        "index.html",
        initial_data=dashboard["markets"],
        initial_system=dashboard["system"],
        initial_pi=dashboard["pi"],
        initial_pi_history=dashboard["pi_history"],
        initial_pi_history_full=dashboard["pi_history_full"],
        initial_quote=dashboard["quote"],
        initial_port_block=dashboard["port_block"],
        initial_error=dashboard["error"],
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/api/prices")
def prices():
    dashboard = fetch_dashboard_data(include_port_block=False)
    status_code = 200 if not dashboard["error"] else 207
    logger.info(
        "Request to /api/prices from %s (errors=%s)",
        request.remote_addr or "unknown",
        bool(dashboard["error"]),
    )

    return jsonify(
        {
            "data": dashboard["markets"],
            "system": dashboard["system"],
            "pi": dashboard["pi"],
            "pi_history": dashboard["pi_history"],
            "pi_history_full": dashboard["pi_history_full"],
            "quote": dashboard["quote"],
            "port_block": dashboard["port_block"],
            "error": dashboard["error"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ), status_code


@app.route("/api/port-block")
def api_port_block():
    payload = _load_port_block_payload()
    status_code = 200 if not payload.get("error") else 207
    logger.info(
        "Request to /api/port-block from %s (errors=%s)",
        request.remote_addr or "unknown",
        bool(payload.get("error")),
    )
    return (
        jsonify(
            {
                "port_block": payload,
                "error": payload.get("error"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        status_code,
    )


if __name__ == "__main__":
    logger.info("Starting Flask server on port 3010")
    app.run(host="127.0.0.1", port=3010, use_reloader=True)
