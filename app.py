import glob
import json
import logging
import re
import random
import socket
import sqlite3
import subprocess
import threading
import time
import math
from urllib.parse import urljoin, urlparse
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
PORT_BLOCK_UFW_REPORT = PORT_BLOCK_ROOT / "ufw_report.md"
PORT_BLOCK_REPORT_DIR = Path(__file__).resolve().parent
PORT_BLOCK_REPORT_GLOB = "port_block_report_*.md"
PORT_BLOCK_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
PORT_BLOCK_EXCLUDED_PLOTS = {"ufw_top_ips"}
CONNECTIVITY_TEST_TARGETS = [("1.1.1.1", 53), ("8.8.8.8", 53)]
CONNECTIVITY_TEST_TIMEOUT = 2.0
INTERNET_MONITOR_DB_PATH = Path("data/internet_monitor.db")
INTERNET_MONITOR_HISTORY_MAX_POINTS = 1800


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
    {
        "name": "Bitcoin",
        "symbol": "BTCUSDT",
        "yf_symbol": "BTC-USD",
        "tradingview": "BINANCE:BTCUSDT",
    },
    {
        "name": "Ethereum",
        "symbol": "ETHUSDT",
        "yf_symbol": "ETH-USD",
        "tradingview": "BINANCE:ETHUSDT",
    },
    {
        "name": "Cardano",
        "symbol": "ADAUSDT",
        "yf_symbol": "ADA-USD",
        "tradingview": "BINANCE:ADAUSDT",
    },
]
STOCKS: List[Dict[str, str]] = [
    {"name": "Marvell Technology (MRVL)", "symbol": "MRVL", "tradingview": "NASDAQ:MRVL"},
    {"name": "Abbott Laboratories (ABT)", "symbol": "ABT", "tradingview": "NYSE:ABT"},
    {"name": "iShares Silver Trust (SLV)", "symbol": "SLV", "tradingview": "NYSEARCA:SLV"},
    {"name": "USD/ARS", "symbol": "ARS=X", "tradingview": "FX_IDC:USDARS"},
]
BINANCE_URL = "https://api.binance.com/api/v3/ticker/24hr"
MARKET_CACHE: Dict[str, object] = {"data": [], "timestamp": None}
MARKET_CACHE_TTL = timedelta(seconds=60)
MARKET_CACHE_LOCK = threading.Lock()
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
BITAXE_BEST_HISTORY_PATH = Path("bitaxe_best_history.jsonl")
BITAXE_BEST_HISTORY_RETENTION = timedelta(days=90)
BITAXE_BEST_HISTORY_MAX_API_POINTS = 800
BITAXE_BEST_HISTORY: List[Dict[str, object]] = []
BITAXE_BEST_HISTORY_LOCK = threading.Lock()
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
QUOTES_REFRESH_INTERVAL = timedelta(days=1)
QUOTE_REQUEST_TIMEOUT = 6
QUOTE_MIN_CHARS = 240
QUOTE_MAX_CHARS = 2400
QUOTE_TARGET_CHARS = 840
QUOTE_CRAWL_LINK_LIMIT = 60
QUOTE_CACHE: List[str] = []
QUOTE_LAST_FETCH: Optional[datetime] = None
QUOTE_LOCK = threading.Lock()
QUOTE_SOURCES = [
    {
        "url": "https://acourseinmiraclesnow.com/read-acim-online/",
        "selector": ".entry-content p, .entry-content li, article p, article li",
        "crawl_links": True,
        "link_include": ("course-miracles-", "/lesson-", "/chapter-", "read-acim-online/"),
    }
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


def _extract_candidates_from_html(html: str, selector: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    tags = soup.select(selector) if selector else []
    if not tags:
        tags = soup.find_all(["blockquote", "p", "li"])

    extracted: List[str] = []
    for tag in tags:
        text = " ".join(tag.get_text(separator=" ").split())
        if not text:
            continue
        extracted.append(text)
    return extracted


def _split_long_text(text: str, min_chars: int, max_chars: int, target_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text] if len(text) >= min_chars else []

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return []

    chunks: List[str] = []
    buffer: List[str] = []
    buffer_len = 0

    def flush(force: bool = False):
        nonlocal buffer, buffer_len
        if not buffer:
            return
        joined = " ".join(buffer).strip()
        if len(joined) >= min_chars and len(joined) <= max_chars:
            chunks.append(joined)
        elif len(joined) > max_chars:
            words = joined.split()
            word_buffer: List[str] = []
            for word in words:
                tentative = (" ".join(word_buffer + [word])).strip()
                if len(tentative) > max_chars and word_buffer:
                    part = " ".join(word_buffer).strip()
                    if len(part) >= min_chars:
                        chunks.append(part)
                    word_buffer = [word]
                else:
                    word_buffer.append(word)
            last = " ".join(word_buffer).strip()
            if len(last) >= min_chars:
                chunks.append(last)
        elif force and chunks:
            # append residual short tail to the previous chunk
            combined = f"{chunks[-1]} {joined}".strip()
            if len(combined) <= max_chars:
                chunks[-1] = combined
        buffer = []
        buffer_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)
        if sentence_len > max_chars:
            flush(force=True)
            words = sentence.split()
            partial: List[str] = []
            for word in words:
                tentative = (" ".join(partial + [word])).strip()
                if len(tentative) > max_chars and partial:
                    part = " ".join(partial).strip()
                    if len(part) >= min_chars:
                        chunks.append(part)
                    partial = [word]
                else:
                    partial.append(word)
            tail = " ".join(partial).strip()
            if len(tail) >= min_chars:
                chunks.append(tail)
            continue

        tentative_len = buffer_len + (1 if buffer else 0) + sentence_len
        should_flush = buffer and (
            tentative_len > max_chars or (buffer_len >= target_chars and sentence_len > min_chars // 2)
        )
        if should_flush:
            flush()
        buffer.append(sentence)
        buffer_len += (1 if buffer_len else 0) + sentence_len

    flush(force=True)
    return chunks


def _expand_quote_candidates(
    candidates: List[str],
    min_chars: int = QUOTE_MIN_CHARS,
    max_chars: int = QUOTE_MAX_CHARS,
    target_chars: int = QUOTE_TARGET_CHARS,
) -> List[str]:
    normalized: List[str] = []
    for raw in candidates:
        text = " ".join(str(raw).split())
        if not text:
            continue
        normalized.append(text)

    expanded: List[str] = []
    short_buffer: List[str] = []
    short_len = 0

    def flush_short_buffer():
        nonlocal short_buffer, short_len
        if not short_buffer:
            return
        merged = " ".join(short_buffer).strip()
        if len(merged) >= min_chars:
            expanded.append(merged[:max_chars].strip())
        short_buffer = []
        short_len = 0

    for text in normalized:
        text_len = len(text)
        if text_len < min_chars:
            short_buffer.append(text)
            short_len += text_len + 1
            if short_len >= target_chars:
                flush_short_buffer()
            continue

        flush_short_buffer()
        if text_len <= max_chars:
            expanded.append(text)
            continue

        expanded.extend(_split_long_text(text, min_chars=min_chars, max_chars=max_chars, target_chars=target_chars))

    flush_short_buffer()

    unique: List[str] = []
    seen = set()
    for item in expanded:
        cleaned = " ".join(item.split())
        if len(cleaned) < min_chars or len(cleaned) > max_chars:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)
    return unique


def _scrape_quotes() -> List[str]:
    scraped: List[str] = []
    headers = {"User-Agent": "status-page/2.0 (+https://matiastrapaglia.space/status/)"}

    for source in QUOTE_SOURCES:
        url = source["url"]
        selector = source.get("selector") or "blockquote, p, li"
        crawl_links = bool(source.get("crawl_links"))
        link_include = tuple(source.get("link_include") or ())

        try:
            resp = requests.get(url, headers=headers, timeout=QUOTE_REQUEST_TIMEOUT)
            resp.raise_for_status()
            scraped.extend(_extract_candidates_from_html(resp.text, selector))

            if crawl_links:
                soup = BeautifulSoup(resp.text, "html.parser")
                base_host = urlparse(url).netloc
                links: List[str] = []
                seen_links = set()
                for anchor in soup.select("a[href]"):
                    href = anchor.get("href") or ""
                    full_url = urljoin(url, href)
                    parsed = urlparse(full_url)
                    if parsed.netloc != base_host:
                        continue
                    if not parsed.scheme.startswith("http"):
                        continue
                    if link_include and not any(token in full_url for token in link_include):
                        continue
                    normalized = full_url.split("#")[0]
                    if normalized in seen_links:
                        continue
                    seen_links.add(normalized)
                    links.append(normalized)
                    if len(links) >= QUOTE_CRAWL_LINK_LIMIT:
                        break

                for link in links:
                    try:
                        link_resp = requests.get(link, headers=headers, timeout=QUOTE_REQUEST_TIMEOUT)
                        link_resp.raise_for_status()
                        scraped.extend(_extract_candidates_from_html(link_resp.text, selector))
                    except requests.RequestException:
                        continue

        except requests.RequestException as exc:
            logger.warning("Could not scrape %s: %s", url, exc)
            continue

    return _expand_quote_candidates(scraped)


def _get_quote_file_mtime() -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(QUOTES_PATH.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _ensure_quotes() -> List[str]:
    global QUOTE_CACHE, QUOTE_LAST_FETCH

    now = datetime.now(timezone.utc)
    with QUOTE_LOCK:
        if QUOTE_CACHE and QUOTE_LAST_FETCH and now - QUOTE_LAST_FETCH < QUOTES_REFRESH_INTERVAL:
            return QUOTE_CACHE

        if not QUOTE_CACHE:
            cached = _load_cached_quotes()
            if cached:
                QUOTE_CACHE = cached
                QUOTE_LAST_FETCH = _get_quote_file_mtime() or now
                if QUOTE_LAST_FETCH and now - QUOTE_LAST_FETCH < QUOTES_REFRESH_INTERVAL:
                    return QUOTE_CACHE

        fresh = _scrape_quotes()
        QUOTE_LAST_FETCH = now
        if fresh:
            QUOTE_CACHE = fresh
            _save_cached_quotes(fresh)
            return QUOTE_CACHE

        if not QUOTE_CACHE:
            QUOTE_CACHE = FALLBACK_QUOTES
            _save_cached_quotes(QUOTE_CACHE)

        return QUOTE_CACHE


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


def _timestamp_to_iso_date(ts: object) -> str:
    if isinstance(ts, datetime):
        return ts.date().isoformat()
    try:
        dt = ts.to_pydatetime()
        return dt.date().isoformat()
    except Exception:
        return str(ts)


def _build_sparkline_series(
    closes: "pd.Series", days: int = 32, max_points: int = 48
) -> List[Dict[str, object]]:
    if closes is None or closes.empty:
        return []

    cutoff = closes.index[-1] - timedelta(days=days)
    recent = closes[closes.index >= cutoff].dropna()
    if recent.empty:
        return []

    series = []
    for ts, value in recent.items():
        numeric_value = _safe_float(value)
        if numeric_value is None:
            continue
        series.append({"t": _timestamp_to_iso_date(ts), "v": numeric_value})

    if len(series) > max_points:
        step = max(1, math.ceil(len(series) / max_points))
        downsampled = series[::step]
        if downsampled[-1] != series[-1]:
            downsampled.append(series[-1])
        series = downsampled

    return series


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
        spark_30d = _build_sparkline_series(closes, days=32, max_points=48)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"No data for {symbol}") from exc

    return {
        "price": _safe_float(latest_price),
        "change_1d": _safe_float(change_1d),
        "change_7d": _safe_float(change_7d),
        "change_30d": _safe_float(change_30d),
        "spark_30d": spark_30d,
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


def _find_latest_port_block_report() -> Optional[Dict[str, object]]:
    latest: Optional[Path] = None
    latest_time: Optional[datetime] = None
    for path in sorted(PORT_BLOCK_REPORT_DIR.glob(PORT_BLOCK_REPORT_GLOB)):
        try:
            mtime_dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if latest_time is None or mtime_dt > latest_time:
            latest_time = mtime_dt
            latest = path
    if not latest or not latest_time:
        return None
    return {
        "filename": latest.name,
        "updated_at": latest_time.isoformat(),
        "url": f"port-block-report/{latest.name}",
    }


def _extract_scanner_stats(report_text: str) -> Dict[str, Optional[int]]:
    if not report_text:
        return {"ip_count": None, "monitoring_count_24h": None}

    lines = [line.strip() for line in report_text.splitlines()]
    in_candidates = False
    ip_count = 0
    monitoring_count_24h = 0
    candidate_pattern = re.compile(r"^-\s+\d{1,3}(?:\.\d{1,3}){3}\s+\((\d+)\)")

    for line in lines:
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("## "):
            in_candidates = lowered == "## candidates"
            continue
        if not in_candidates:
            continue

        match = candidate_pattern.match(line)
        if not match:
            continue

        ip_count += 1
        monitoring_count_24h += int(match.group(1))

    return {
        "ip_count": ip_count if ip_count > 0 else None,
        "monitoring_count_24h": monitoring_count_24h if monitoring_count_24h > 0 else None,
    }


def _extract_scanner_ip_count(report_text: str) -> Optional[int]:
    return _extract_scanner_stats(report_text).get("ip_count")


def _extract_scanner_monitoring_count(report_text: str) -> Optional[int]:
    return _extract_scanner_stats(report_text).get("monitoring_count_24h")


def _read_scanner_stats_from_report(report: Optional[Dict[str, object]]) -> Dict[str, Optional[int]]:
    if not report:
        return {"ip_count": None, "monitoring_count_24h": None}
    filename = report.get("filename")
    if not filename:
        return {"ip_count": None, "monitoring_count_24h": None}

    report_path = (PORT_BLOCK_REPORT_DIR / str(filename)).resolve()
    root = PORT_BLOCK_REPORT_DIR.resolve()
    if root not in report_path.parents and report_path != root:
        return {"ip_count": None, "monitoring_count_24h": None}

    try:
        report_text = report_path.read_text(encoding="utf-8")
    except OSError:
        return {"ip_count": None, "monitoring_count_24h": None}

    return _extract_scanner_stats(report_text)


def _extract_total_blocks_24h(report_text: str) -> Optional[int]:
    if not report_text:
        return None

    match = re.search(r"^-\s*Total\s+blocks:\s*([0-9][0-9,]*)\s*$", report_text, flags=re.MULTILINE | re.IGNORECASE)
    if not match:
        return None

    try:
        total_blocks = int(match.group(1).replace(",", ""))
    except ValueError:
        return None

    return total_blocks if total_blocks > 0 else None


def _read_total_blocks_from_ufw_report() -> Optional[int]:
    try:
        report_text = PORT_BLOCK_UFW_REPORT.read_text(encoding="utf-8")
    except OSError:
        return None
    return _extract_total_blocks_24h(report_text)


def _extract_unique_source_ips_24h(report_text: str) -> Optional[int]:
    if not report_text:
        return None

    match = re.search(r"^-\s*Unique\s+source\s+IPs:\s*([0-9][0-9,]*)\s*$", report_text, flags=re.MULTILINE | re.IGNORECASE)
    if not match:
        return None

    try:
        unique_source_ips = int(match.group(1).replace(",", ""))
    except ValueError:
        return None

    return unique_source_ips if unique_source_ips > 0 else None


def _read_unique_source_ips_from_ufw_report() -> Optional[int]:
    try:
        report_text = PORT_BLOCK_UFW_REPORT.read_text(encoding="utf-8")
    except OSError:
        return None
    return _extract_unique_source_ips_24h(report_text)


def _load_port_block_payload() -> Dict[str, object]:
    plots: List[Dict[str, object]] = []
    errors: List[str] = []
    latest_plot_time: Optional[datetime] = None

    try:
        for path in sorted(PORT_BLOCK_PLOTS.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in PORT_BLOCK_ALLOWED_SUFFIXES:
                continue
            if path.stem in PORT_BLOCK_EXCLUDED_PLOTS:
                continue
            relative_path = path.relative_to(PORT_BLOCK_ROOT)
            try:
                mtime_dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                mtime = mtime_dt.isoformat()
                if latest_plot_time is None or mtime_dt > latest_plot_time:
                    latest_plot_time = mtime_dt
            except OSError:
                mtime = None
            plots.append(
                {
                    "filename": str(relative_path),
                    "label": path.stem.replace("_", " ").title(),
                    "updated_at": mtime,
                    "url": f"port-block/{relative_path}",
                }
            )
    except OSError as exc:
        errors.append(f"Could not read plots: {exc}")

    report = _find_latest_port_block_report()
    scanner_stats = _read_scanner_stats_from_report(report)
    total_blocks_24h = _read_total_blocks_from_ufw_report()
    unique_source_ips_24h = _read_unique_source_ips_from_ufw_report()

    return {
        "plots": plots,
        "updated_at": latest_plot_time.isoformat() if latest_plot_time else None,
        "report": report,
        "scanner_ip_count": unique_source_ips_24h or scanner_stats.get("ip_count"),
        "monitoring_count_24h": total_blocks_24h or scanner_stats.get("monitoring_count_24h"),
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
        "bitaxe_best_history": _build_bitaxe_best_history_series(),
        "pi": pi_stats,
        "pi_history": _build_pi_history_series(),
        "pi_history_full": _build_pi_full_history_series(),
        "internet_monitor_history": _load_internet_monitor_history(),
        "quote": {"text": quote} if quote else None,
        "port_block": port_block if include_port_block else None,
        "error": "; ".join(errors) if errors else None,
    }


def fetch_market_data() -> List[Dict[str, float]]:
    """Fetch price and 24h change for crypto and stocks with a short-lived cache."""
    now = datetime.now(timezone.utc)
    with MARKET_CACHE_LOCK:
        cached_data = MARKET_CACHE.get("data") or []
        cached_at = MARKET_CACHE.get("timestamp")

    if cached_data and cached_at and now - cached_at < MARKET_CACHE_TTL:
        return cached_data

    try:
        crypto_data = _fetch_from_binance()
        stock_data = _fetch_from_yfinance()
        combined = crypto_data + stock_data
    except RuntimeError as exc:
        if cached_data:
            logger.warning("Using cached market data after error: %s", exc)
            return cached_data
        raise

    with MARKET_CACHE_LOCK:
        MARKET_CACHE["data"] = combined
        MARKET_CACHE["timestamp"] = now

    return combined


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
                spark_30d = snapshot.get("spark_30d")
            except RuntimeError as exc:
                logger.warning("Could not fetch weekly/monthly data for %s: %s", yf_symbol, exc)
                spark_30d = []
        else:
            spark_30d = []

        rows.append(
            {
                "id": coin["symbol"],
                "name": coin["name"],
                "price": price,
                "change": change_1d,
                "change_7d": change_7d,
                "change_30d": change_30d,
                "spark_30d": spark_30d,
                "tradingview": coin.get("tradingview"),
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
                    "spark_30d": snapshot.get("spark_30d") or [],
                    "tradingview": stock.get("tradingview"),
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
    _record_bitaxe_best_history(payload.get("bestSessionDiff"))

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


def _serialize_bitaxe_entry(entry: Dict[str, object]) -> Dict[str, object]:
    ts = entry.get("ts")
    return {
        "ts": ts.isoformat() if isinstance(ts, datetime) else ts,
        "best_session": entry.get("best_session"),
        "display": entry.get("display"),
    }


def _rewrite_bitaxe_best_history_file(entries) -> None:
    try:
        with BITAXE_BEST_HISTORY_PATH.open("w", encoding="utf-8") as handle:
            for entry in entries:
                json.dump(_serialize_bitaxe_entry(entry), handle, ensure_ascii=False)
                handle.write("\n")
    except OSError as exc:
        logger.warning("Could not compact Bitaxe history: %s", exc)


def _persist_bitaxe_best_entry(entry: Dict[str, object]) -> None:
    payload = _serialize_bitaxe_entry(entry)
    try:
        with BITAXE_BEST_HISTORY_PATH.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
    except OSError as exc:
        logger.warning("Could not save Bitaxe history: %s", exc)


def _load_bitaxe_best_history_from_disk() -> None:
    if not BITAXE_BEST_HISTORY_PATH.exists():
        return

    entries: List[Dict[str, object]] = []
    retention_cutoff = (
        datetime.now(timezone.utc) - BITAXE_BEST_HISTORY_RETENTION if BITAXE_BEST_HISTORY_RETENTION else None
    )
    try:
        with BITAXE_BEST_HISTORY_PATH.open("r", encoding="utf-8") as handle:
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
                    continue

                best_session = _safe_float(payload.get("best_session"))
                if best_session is None:
                    continue

                display = payload.get("display")
                entries.append({"ts": ts, "best_session": best_session, "display": display})
    except OSError as exc:
        logger.warning("Could not read Bitaxe history: %s", exc)
        return

    entries.sort(key=lambda item: item["ts"])
    with BITAXE_BEST_HISTORY_LOCK:
        BITAXE_BEST_HISTORY.clear()
        BITAXE_BEST_HISTORY.extend(entries)


def _record_bitaxe_best_history(best_session_raw) -> None:
    best_session_value = _parse_difficulty(best_session_raw)
    if best_session_value is None or best_session_value <= 0:
        return

    now = datetime.now(timezone.utc)
    display_value = (
        _format_difficulty_display(best_session_raw)
        or _format_difficulty_display(best_session_value)
        or str(best_session_raw)
    )

    pruned_snapshot: Optional[List[Dict[str, object]]] = None
    with BITAXE_BEST_HISTORY_LOCK:
        last = BITAXE_BEST_HISTORY[-1] if BITAXE_BEST_HISTORY else None
        if last and _safe_float(last.get("best_session")) == best_session_value:
            return

        entry = {"ts": now, "best_session": best_session_value, "display": display_value}
        BITAXE_BEST_HISTORY.append(entry)

        if BITAXE_BEST_HISTORY_RETENTION:
            cutoff = now - BITAXE_BEST_HISTORY_RETENTION
            removed = 0
            while BITAXE_BEST_HISTORY and BITAXE_BEST_HISTORY[0]["ts"] < cutoff:
                BITAXE_BEST_HISTORY.pop(0)
                removed += 1
            if removed:
                pruned_snapshot = list(BITAXE_BEST_HISTORY)

    _persist_bitaxe_best_entry(entry)
    if pruned_snapshot is not None:
        _rewrite_bitaxe_best_history_file(pruned_snapshot)


def _build_bitaxe_best_history_payload(entries: List[Dict[str, object]]) -> Dict[str, List[object]]:
    labels: List[str] = []
    values: List[Optional[float]] = []
    displays: List[Optional[str]] = []

    for entry in entries:
        ts = entry.get("ts")
        if not ts:
            continue
        labels.append(ts.isoformat() if isinstance(ts, datetime) else str(ts))
        value = _safe_float(entry.get("best_session"))
        values.append(value)
        display_value = entry.get("display") or _format_difficulty_display(value)
        displays.append(display_value)

    return {
        "labels": labels,
        "best_session": values,
        "display": displays,
    }


def _build_bitaxe_best_history_series() -> Dict[str, List[object]]:
    with BITAXE_BEST_HISTORY_LOCK:
        entries = list(BITAXE_BEST_HISTORY)
    downsampled = _downsample_entries(entries, BITAXE_BEST_HISTORY_MAX_API_POINTS)
    return _build_bitaxe_best_history_payload(downsampled)


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

    total = len(entries)
    step = max(1, math.ceil(total / max_points))

    base_indices = set(range(0, total, step))
    base_indices.add(total - 1)

    forced_indices: set[int] = {0, total - 1}
    for idx, entry in enumerate(entries):
        online = entry.get("online")
        if online is False:
            forced_indices.update({idx, max(0, idx - 1), min(total - 1, idx + 1)})
        if idx > 0:
            prev_online = entries[idx - 1].get("online")
            if online != prev_online:
                forced_indices.update({idx - 1, idx})

    keep_indices = base_indices | forced_indices
    if len(keep_indices) <= max_points:
        return [entries[i] for i in sorted(keep_indices)]

    forced_sorted = sorted(forced_indices)
    if len(forced_sorted) >= max_points:
        step_forced = max(1, math.ceil(len(forced_sorted) / max_points))
        forced_sampled = forced_sorted[::step_forced]
        if forced_sampled and forced_sampled[-1] != forced_sorted[-1]:
            forced_sampled.append(forced_sorted[-1])
        return [entries[i] for i in forced_sampled]

    remaining = [i for i in sorted(base_indices) if i not in forced_indices]
    slots = max_points - len(forced_sorted)
    if not remaining or slots <= 0:
        return [entries[i] for i in forced_sorted]

    step_remaining = max(1, math.ceil(len(remaining) / slots))
    remaining_sampled = remaining[::step_remaining]
    keep = sorted(set(forced_sorted) | set(remaining_sampled))
    return [entries[i] for i in keep]


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
            "updated_at": datetime.now(timezone.utc).isoformat(),
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


_load_bitaxe_best_history_from_disk()
_load_pi_full_history_from_disk()
_start_pi_sampler()


def _load_internet_monitor_history(limit: int = INTERNET_MONITOR_HISTORY_MAX_POINTS) -> Dict[str, List[object]]:
    db_path = INTERNET_MONITOR_DB_PATH
    if not db_path.exists():
        return {"labels": [], "speed_kbps": [], "status": []}

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT timestamp_utc, speed_kbps, status
                FROM download_samples
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 5000)),),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Could not load internet monitor history: %s", exc)
        return {"labels": [], "speed_kbps": [], "status": []}

    ordered = list(reversed(rows))
    labels = [str(row["timestamp_utc"]) for row in ordered]
    speed_kbps = [_safe_float(row["speed_kbps"]) for row in ordered]
    status = [str(row["status"]) if row["status"] is not None else None for row in ordered]
    return {
        "labels": labels,
        "speed_kbps": speed_kbps,
        "status": status,
    }


def _load_internet_monitor_payload(limit: int = 120) -> Dict[str, object]:
    db_path = INTERNET_MONITOR_DB_PATH
    if not db_path.exists():
        return {
            "available": False,
            "db_path": str(db_path),
            "latest": None,
            "samples": [],
            "error": "Internet monitor database not found",
        }

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            latest_row = conn.execute(
                """
                SELECT timestamp_utc, url, limit_rate, range_bytes,
                       speed_bps, speed_kbps, time_total_s, http_code,
                       status, error, curl_exit_code
                FROM download_samples
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

            rows = conn.execute(
                """
                SELECT timestamp_utc, speed_kbps, time_total_s, http_code,
                       status, curl_exit_code
                FROM download_samples
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()
    except sqlite3.Error as exc:
        return {
            "available": False,
            "db_path": str(db_path),
            "latest": None,
            "samples": [],
            "error": f"Could not read internet monitor DB: {exc}",
        }

    samples = [dict(row) for row in reversed(rows)]
    latest = dict(latest_row) if latest_row else None

    return {
        "available": True,
        "db_path": str(db_path),
        "latest": latest,
        "samples": samples,
        "error": None,
    }


@app.before_request
def _require_token():
    if request.endpoint == "static":
        return None
    if request.endpoint in {"port_block_asset", "port_block_report", "port_block_report_latest"}:
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


@app.route("/port-block-report/latest")
def port_block_report_latest():
    report = _find_latest_port_block_report()
    if not report:
        abort(404)
    target = (PORT_BLOCK_REPORT_DIR / report["filename"]).resolve()
    if not target.exists() or not target.is_file():
        abort(404)
    try:
        response = send_file(target, mimetype="text/markdown")
    except OSError:
        abort(404)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/port-block-report/<path:filename>")
def port_block_report(filename):
    if not filename.startswith("port_block_report_") or not filename.endswith(".md"):
        abort(404)
    target = (PORT_BLOCK_REPORT_DIR / filename).resolve()
    root = PORT_BLOCK_REPORT_DIR.resolve()
    if root not in target.parents and target != root:
        abort(404)
    if not target.exists() or not target.is_file():
        abort(404)
    try:
        response = send_file(target, mimetype="text/markdown")
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
        initial_bitaxe_best_history=dashboard["bitaxe_best_history"],
        initial_pi=dashboard["pi"],
        initial_pi_history=dashboard["pi_history"],
        initial_pi_history_full=dashboard["pi_history_full"],
        initial_internet_monitor_history=dashboard["internet_monitor_history"],
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
            "bitaxe_best_history": dashboard["bitaxe_best_history"],
            "pi": dashboard["pi"],
            "pi_history": dashboard["pi_history"],
            "pi_history_full": dashboard["pi_history_full"],
            "internet_monitor_history": dashboard["internet_monitor_history"],
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


@app.route("/api/internet-monitor")
def api_internet_monitor():
    limit = request.args.get("limit", default=120, type=int)
    payload = _load_internet_monitor_payload(limit=limit)
    status_code = 200 if not payload.get("error") else 207
    logger.info(
        "Request to /api/internet-monitor from %s (errors=%s)",
        request.remote_addr or "unknown",
        bool(payload.get("error")),
    )
    return (
        jsonify(
            {
                "internet_monitor": payload,
                "error": payload.get("error"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        status_code,
    )


if __name__ == "__main__":
    logger.info("Starting Flask server on port 3010")
    app.run(host="127.0.0.1", port=3010, use_reloader=True)
