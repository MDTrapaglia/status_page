#!/usr/bin/env python3
"""Monitor continuo de descarga limitada y persistencia en SQLite.

Uso rápido:
  python scripts/internet_speed_logger.py

Variables de entorno opcionales:
  MONITOR_URL=https://proof.ovh.net/files/10Mb.dat
  LIMIT_RATE=80K
  RANGE_BYTES=1048576
  INTERVAL_SECONDS=15
  MAX_TIME_SECONDS=60
  DB_PATH=data/internet_monitor.db
"""

from __future__ import annotations

import os
import shlex
import signal
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "internet_monitor.db"))).expanduser()
MONITOR_URL = os.getenv("MONITOR_URL", "http://ipv4.download.thinkbroadband.com/5MB.zip")
LIMIT_RATE = os.getenv("LIMIT_RATE", "80K")
RANGE_BYTES = int(os.getenv("RANGE_BYTES", "1048576"))
INTERVAL_SECONDS = float(os.getenv("INTERVAL_SECONDS", "15"))
MAX_TIME_SECONDS = int(os.getenv("MAX_TIME_SECONDS", "60"))

STOP = False


def _on_signal(signum, _frame):
    global STOP
    STOP = True
    print(f"\nSignal {signum} recibido. Cerrando monitor…")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS download_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            url TEXT NOT NULL,
            limit_rate TEXT NOT NULL,
            range_bytes INTEGER NOT NULL,
            speed_bps REAL NOT NULL,
            speed_kbps REAL NOT NULL,
            time_total_s REAL NOT NULL,
            http_code INTEGER NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            curl_exit_code INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_download_samples_timestamp
        ON download_samples(timestamp_utc)
        """
    )
    conn.commit()


def _run_probe() -> Dict[str, object]:
    cmd = [
        "curl",
        "-L",
        "--silent",
        "--show-error",
        "--output",
        "/dev/null",
        "--range",
        f"0-{RANGE_BYTES - 1}",
        "--limit-rate",
        LIMIT_RATE,
        "--max-time",
        str(MAX_TIME_SECONDS),
        "--write-out",
        "%{speed_download} %{time_total} %{http_code}",
        MONITOR_URL,
    ]

    completed = subprocess.run(cmd, text=True, capture_output=True)
    raw = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if completed.returncode == 0:
        try:
            speed_bps_s, time_total_s, http_code_s = raw.split()
            speed_bps = float(speed_bps_s)
            time_total = float(time_total_s)
            http_code = int(http_code_s)
            return {
                "status": "ok",
                "speed_bps": speed_bps,
                "speed_kbps": round(speed_bps / 1024, 2),
                "time_total_s": time_total,
                "http_code": http_code,
                "error": None,
                "curl_exit_code": 0,
            }
        except (ValueError, TypeError) as exc:
            err = f"parse_error: {exc}; raw={raw!r}"
            return {
                "status": "error",
                "speed_bps": 0.0,
                "speed_kbps": 0.0,
                "time_total_s": 0.0,
                "http_code": 0,
                "error": err,
                "curl_exit_code": 98,
            }

    err = f"{stderr} {raw}".strip()
    return {
        "status": "error",
        "speed_bps": 0.0,
        "speed_kbps": 0.0,
        "time_total_s": 0.0,
        "http_code": 0,
        "error": err[:2000] if err else "curl failed",
        "curl_exit_code": int(completed.returncode),
    }


def _insert_sample(conn: sqlite3.Connection, sample: Dict[str, object]) -> None:
    conn.execute(
        """
        INSERT INTO download_samples (
            timestamp_utc, url, limit_rate, range_bytes,
            speed_bps, speed_kbps, time_total_s, http_code,
            status, error, curl_exit_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _now_iso(),
            MONITOR_URL,
            LIMIT_RATE,
            RANGE_BYTES,
            sample["speed_bps"],
            sample["speed_kbps"],
            sample["time_total_s"],
            sample["http_code"],
            sample["status"],
            sample["error"],
            sample["curl_exit_code"],
        ),
    )
    conn.commit()


def main() -> int:
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        _ensure_db(conn)

        print("Iniciando internet_speed_logger…")
        print(f"DB_PATH={DB_PATH}")
        print(f"MONITOR_URL={MONITOR_URL}")
        print(f"LIMIT_RATE={LIMIT_RATE}")
        print(f"RANGE_BYTES={RANGE_BYTES}")
        print(f"INTERVAL_SECONDS={INTERVAL_SECONDS}")
        print(f"MAX_TIME_SECONDS={MAX_TIME_SECONDS}")
        print(f"Comando base: curl --limit-rate {shlex.quote(LIMIT_RATE)} --range 0-{RANGE_BYTES - 1}")
        print("Ctrl+C para detener.")

        while not STOP:
            sample = _run_probe()
            _insert_sample(conn, sample)

            ts = datetime.now().astimezone().isoformat(timespec="seconds")
            if sample["status"] == "ok":
                print(
                    f"[{ts}] OK speed={sample['speed_kbps']:.2f} KB/s "
                    f"time={sample['time_total_s']:.3f}s http={sample['http_code']}"
                )
            else:
                print(
                    f"[{ts}] ERROR curl_exit={sample['curl_exit_code']} "
                    f"msg={(sample['error'] or '')[:160]}"
                )

            if STOP:
                break
            time.sleep(INTERVAL_SECONDS)

    print("Monitor detenido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
