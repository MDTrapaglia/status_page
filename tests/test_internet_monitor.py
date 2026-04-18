import sqlite3
from pathlib import Path

from app import AUTH_TOKEN, app


def _seed_monitor_db(db_path: Path):
    conn = sqlite3.connect(db_path)
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
    conn.executemany(
        """
        INSERT INTO download_samples (
            timestamp_utc, url, limit_rate, range_bytes,
            speed_bps, speed_kbps, time_total_s, http_code,
            status, error, curl_exit_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "2026-04-18T02:00:00+00:00",
                "http://example.test/file.bin",
                "80K",
                1024,
                40960.0,
                40.0,
                2.1,
                206,
                "ok",
                None,
                0,
            ),
            (
                "2026-04-18T02:00:02+00:00",
                "http://example.test/file.bin",
                "80K",
                1024,
                51200.0,
                50.0,
                2.0,
                206,
                "ok",
                None,
                0,
            ),
        ],
    )
    conn.commit()
    conn.close()


def test_load_internet_monitor_history_from_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "internet_monitor.db"
    _seed_monitor_db(db_path)

    monkeypatch.setattr("app.INTERNET_MONITOR_DB_PATH", db_path)

    from app import _load_internet_monitor_history

    series = _load_internet_monitor_history(limit=10)

    assert series["labels"] == [
        "2026-04-18T02:00:00+00:00",
        "2026-04-18T02:00:02+00:00",
    ]
    assert series["speed_kbps"] == [40.0, 50.0]
    assert series["status"] == ["ok", "ok"]


def test_status_page_includes_internet_monitor_series(monkeypatch):
    dashboard = {
        "markets": [],
        "system": None,
        "bitaxe_best_history": {"labels": [], "best_session": [], "display": []},
        "pi": None,
        "pi_history": {"labels": []},
        "pi_history_full": {"labels": []},
        "internet_monitor_history": {
            "labels": ["2026-04-18T02:00:00+00:00"],
            "speed_kbps": [42.0],
            "status": ["ok"],
        },
        "quote": None,
        "port_block": {"plots": [], "updated_at": None, "report": None, "error": None},
        "error": None,
    }
    monkeypatch.setattr("app.fetch_dashboard_data", lambda include_port_block=True: dashboard)

    client = app.test_client()
    response = client.get(f"/?token={AUTH_TOKEN}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "initialInternetMonitorHistory" in html
    assert "Internet (KB/s)" in html
