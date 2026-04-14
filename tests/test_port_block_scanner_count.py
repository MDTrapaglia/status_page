import os
from pathlib import Path

from app import _extract_scanner_ip_count, _load_port_block_payload


def test_extract_scanner_ip_count_counts_candidates_section_only():
    report_text = """# Port-block report (2026-04-12)

## Policy
- Window: last 24 hours

## Candidates
- 1.1.1.1 (120)
- 2.2.2.2 (80)
- 3.3.3.3 (30)

## Applied rules
- 1.1.1.1 (120) → OK
- 2.2.2.2 (80) → OK
"""

    assert _extract_scanner_ip_count(report_text) == 3


def test_load_port_block_payload_exposes_scanner_ip_count_from_latest_report(tmp_path, monkeypatch):
    report_old = tmp_path / "port_block_report_2026-04-10.md"
    report_new = tmp_path / "port_block_report_2026-04-11.md"
    report_old.write_text("## Candidates\n- 10.0.0.1 (20)\n", encoding="utf-8")
    report_new.write_text("## Candidates\n- 8.8.8.8 (40)\n- 9.9.9.9 (25)\n", encoding="utf-8")

    # make sure the latest report is deterministic by mtime
    old_ts = 1_700_000_000
    new_ts = old_ts + 10
    os.utime(report_old, (old_ts, old_ts))
    os.utime(report_new, (new_ts, new_ts))

    plots_root = tmp_path / "port_block"
    plots_dir = plots_root / "ufw_plots"
    plots_dir.mkdir(parents=True)

    monkeypatch.setattr("app.PORT_BLOCK_REPORT_DIR", tmp_path)
    monkeypatch.setattr("app.PORT_BLOCK_ROOT", plots_root)
    monkeypatch.setattr("app.PORT_BLOCK_PLOTS", plots_dir)

    payload = _load_port_block_payload()

    assert payload["scanner_ip_count"] == 2
