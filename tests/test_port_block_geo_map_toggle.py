from app import AUTH_TOKEN, app, _resolve_port_block_asset_target


def test_resolve_port_block_asset_target_prefers_no_labels_all_sources_variant(tmp_path):
    root = tmp_path / "port_block"
    default_map = root / "ufw_plots" / "ufw_geo_map.jpg"
    all_sources_map = root / "ufw_plots" / "ufw_geo_map_all_sources.jpg"
    all_sources_no_labels_map = root / "ufw_plots" / "ufw_geo_map_all_sources_no_labels.jpg"
    all_sources_no_labels_map.parent.mkdir(parents=True)
    default_map.write_bytes(b"default")
    all_sources_map.write_bytes(b"all")
    all_sources_no_labels_map.write_bytes(b"all-no-labels")

    target = _resolve_port_block_asset_target(
        root,
        "ufw_plots/ufw_geo_map.jpg",
        all_sources=True,
        hide_labels=True,
    )

    assert target == all_sources_no_labels_map


def test_resolve_port_block_asset_target_falls_back_to_all_sources_map_when_no_labels_missing(tmp_path):
    root = tmp_path / "port_block"
    default_map = root / "ufw_plots" / "ufw_geo_map.jpg"
    all_sources_map = root / "ufw_plots" / "ufw_geo_map_all_sources.jpg"
    all_sources_map.parent.mkdir(parents=True)
    default_map.write_bytes(b"default")
    all_sources_map.write_bytes(b"all")

    target = _resolve_port_block_asset_target(
        root,
        "ufw_plots/ufw_geo_map.jpg",
        all_sources=True,
        hide_labels=True,
    )

    assert target == all_sources_map


def test_resolve_port_block_asset_target_falls_back_to_default_map(tmp_path):
    root = tmp_path / "port_block"
    default_map = root / "ufw_plots" / "ufw_geo_map.jpg"
    default_map.parent.mkdir(parents=True)
    default_map.write_bytes(b"default")

    target = _resolve_port_block_asset_target(root, "ufw_plots/ufw_geo_map.jpg", all_sources=True)

    assert target == default_map


def test_status_page_contains_ufw_geo_map_all_sources_toggle(monkeypatch):
    dashboard = {
        "markets": [],
        "system": None,
        "bitaxe_best_history": {"labels": [], "best_session": [], "display": []},
        "pi": None,
        "pi_history": {"labels": []},
        "pi_history_full": {"labels": []},
        "internet_monitor_history": {"labels": [], "speed_kbps": [], "status": []},
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
    assert 'id="ufw-geo-map-all-sources-toggle"' in html
    assert 'id="ufw-geo-map-all-sources-label"' in html
    assert "all_sources=1&hide_labels=1" in html


def test_port_block_asset_serves_no_labels_geo_map_variant_when_requested(tmp_path, monkeypatch):
    root = tmp_path / "port_block"
    default_map = root / "ufw_plots" / "ufw_geo_map.jpg"
    all_sources_map = root / "ufw_plots" / "ufw_geo_map_all_sources.jpg"
    all_sources_no_labels_map = root / "ufw_plots" / "ufw_geo_map_all_sources_no_labels.jpg"
    default_map.parent.mkdir(parents=True)
    default_map.write_bytes(b"default-map")
    all_sources_map.write_bytes(b"all-sources-map")
    all_sources_no_labels_map.write_bytes(b"all-sources-no-labels-map")

    monkeypatch.setattr("app.PORT_BLOCK_ROOT", root)

    client = app.test_client()
    response = client.get(
        f"/port-block/ufw_plots/ufw_geo_map.jpg?token={AUTH_TOKEN}&all_sources=1&hide_labels=1"
    )

    assert response.status_code == 200
    assert response.data == b"all-sources-no-labels-map"