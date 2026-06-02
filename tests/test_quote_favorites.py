import json

import app as status_app
from app import AUTH_TOKEN


EMPTY_HISTORY = {"labels": []}
EMPTY_INTERNET = {"labels": [], "speed_kbps": [], "status": []}
EMPTY_BITAXE = {"labels": [], "best_session": [], "display": []}


def _stub_dashboard_dependencies(monkeypatch):
    monkeypatch.setattr(status_app, "fetch_market_data", lambda: [])
    monkeypatch.setattr(status_app, "_fetch_system_snapshot", lambda: None)
    monkeypatch.setattr(status_app, "_fetch_pi_stats", lambda check_connectivity=False: (None, None))
    monkeypatch.setattr(status_app, "_build_bitaxe_best_history_series", lambda: EMPTY_BITAXE)
    monkeypatch.setattr(status_app, "_build_pi_history_series", lambda: EMPTY_HISTORY)
    monkeypatch.setattr(status_app, "_build_pi_full_history_series", lambda: EMPTY_HISTORY)
    monkeypatch.setattr(status_app, "_load_internet_monitor_history", lambda: EMPTY_INTERNET)


def test_fetch_dashboard_data_marks_daily_quote_as_favorite(tmp_path, monkeypatch):
    favorites_path = tmp_path / "quote_favorites.json"
    favorites_path.write_text(json.dumps(["Peace is the goal."]), encoding="utf-8")

    monkeypatch.setattr(status_app, "QUOTE_FAVORITES_PATH", favorites_path, raising=False)
    monkeypatch.setattr(status_app, "QUOTE_FAVORITES_CACHE", [], raising=False)
    _stub_dashboard_dependencies(monkeypatch)
    monkeypatch.setattr(status_app, "_get_daily_quote", lambda: "Peace is the goal.")

    dashboard = status_app.fetch_dashboard_data(include_port_block=False)

    assert dashboard["quote"] == {
        "text": "Peace is the goal.",
        "is_favorite": True,
        "favorites": ["Peace is the goal."],
        "favorites_count": 1,
    }


def test_quote_favorite_api_persists_new_favorites(tmp_path, monkeypatch):
    favorites_path = tmp_path / "quote_favorites.json"

    monkeypatch.setattr(status_app, "QUOTE_FAVORITES_PATH", favorites_path, raising=False)
    monkeypatch.setattr(status_app, "QUOTE_FAVORITES_CACHE", [], raising=False)

    client = status_app.app.test_client()
    response = client.post(
        f"/api/quote-favorites?token={AUTH_TOKEN}",
        json={"quote": "Only love is real.", "favorite": True},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "favorite": True,
        "favorites": ["Only love is real."],
        "favorites_count": 1,
        "quote": "Only love is real.",
    }
    assert json.loads(favorites_path.read_text(encoding="utf-8")) == ["Only love is real."]


def test_status_page_contains_quote_favorite_controls(monkeypatch):
    dashboard = {
        "markets": [],
        "system": None,
        "bitaxe_best_history": EMPTY_BITAXE,
        "pi": None,
        "pi_history": EMPTY_HISTORY,
        "pi_history_full": EMPTY_HISTORY,
        "internet_monitor_history": EMPTY_INTERNET,
        "quote": {
            "text": "Nothing real can be threatened.",
            "is_favorite": True,
            "favorites": [
                "Nothing real can be threatened.",
                "Only love is real.",
            ],
            "favorites_count": 2,
        },
        "port_block": {"plots": [], "updated_at": None, "report": None, "error": None},
        "error": None,
    }
    monkeypatch.setattr(status_app, "fetch_dashboard_data", lambda include_port_block=True: dashboard)

    client = status_app.app.test_client()
    response = client.get(f"/?token={AUTH_TOKEN}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="quote-favorite-toggle"' in html
    assert 'id="quote-next-favorite"' in html
    assert 'id="quote-favorites-count"' in html
