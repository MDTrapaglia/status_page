from app import AUTH_TOKEN, app


def test_status_page_contains_prominent_scanner_highlight_placeholder(monkeypatch):
    dashboard = {
        "markets": [],
        "system": None,
        "bitaxe_best_history": {"labels": [], "best_session": [], "display": []},
        "pi": None,
        "pi_history": {"labels": []},
        "pi_history_full": {"labels": []},
        "quote": None,
        "port_block": {
            "plots": [],
            "updated_at": None,
            "report": None,
            "scanner_ip_count": 19,
            "error": None,
        },
        "error": None,
    }
    monkeypatch.setattr("app.fetch_dashboard_data", lambda include_port_block=True: dashboard)

    client = app.test_client()
    response = client.get(f"/?token={AUTH_TOKEN}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="port-block-scanner-highlight"' in html
    assert 'id="port-block-scanner-value"' in html
