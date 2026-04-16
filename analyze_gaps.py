#!/usr/bin/env python3
"""Analiza gaps y caídas en el historial de Pi"""

import json
from datetime import datetime

gaps = []
offline_events = []
prev_ts = None
total_entries = 0
entries_with_online = 0

with open('/home/mtrapaglia/projects/status_page/pi_history_full.jsonl', 'r') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except:
            continue

        total_entries += 1
        ts = datetime.fromisoformat(entry['ts'])

        # Detectar offline
        if 'online' in entry:
            entries_with_online += 1
            if entry.get('online') == False:
                offline_events.append({
                    'ts': entry['ts'],
                    'cpu': entry.get('cpu'),
                    'ram': entry.get('ram')
                })

        # Detectar gaps (pérdidas de tensión)
        if prev_ts:
            gap_seconds = (ts - prev_ts).total_seconds()
            if gap_seconds > 150:  # Umbral de 2.5 minutos
                gaps.append({
                    'start': prev_ts.isoformat(),
                    'end': ts.isoformat(),
                    'duration_seconds': gap_seconds,
                    'duration_minutes': round(gap_seconds / 60, 1)
                })

        prev_ts = ts

print(f"=== ESTADÍSTICAS GENERALES ===")
print(f"Total de entradas: {total_entries}")
print(f"Entradas con campo 'online': {entries_with_online}")
print(f"Período de monitoreo: {round((total_entries * 60) / (60 * 24), 1)} días aprox.")

print(f"\n=== CAÍDAS DE INTERNET (online=false) ===")
print(f"Total: {len(offline_events)}")
for event in offline_events:
    print(f"  {event['ts']} - CPU: {event['cpu']}%, RAM: {event['ram']}%")

print(f"\n=== GAPS DE TENSIÓN (>2.5 min sin datos) ===")
print(f"Total: {len(gaps)}")
for gap in gaps[:20]:  # Mostrar primeros 20
    print(f"  {gap['start']} → {gap['end']}")
    print(f"    Duración: {gap['duration_minutes']} minutos ({gap['duration_seconds']} seg)")

if len(gaps) > 20:
    print(f"\n  ... y {len(gaps) - 20} gaps más")
