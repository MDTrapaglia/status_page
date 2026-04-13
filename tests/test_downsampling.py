#!/usr/bin/env python3
"""Prueba del nuevo algoritmo de downsampling"""

import json
import math
from datetime import datetime

# Simular la nueva función _downsample_entries
def _downsample_entries(entries, max_points):
    if max_points <= 0 or len(entries) <= max_points:
        return list(entries)

    # Downsampling básico
    step = max(1, math.ceil(len(entries) / max_points))
    sampled_indices = set(range(0, len(entries), step))

    # Asegurar que el último punto esté incluido
    sampled_indices.add(len(entries) - 1)

    # Preservar puntos críticos: caídas de internet (online=false)
    for i, entry in enumerate(entries):
        if entry.get("online") is False:
            sampled_indices.add(i)
            # Incluir también el punto anterior y siguiente para contexto
            if i > 0:
                sampled_indices.add(i - 1)
            if i < len(entries) - 1:
                sampled_indices.add(i + 1)

    # Preservar puntos que marcan grandes gaps (pérdidas de tensión)
    GAP_THRESHOLD_SECONDS = 150
    for i in range(1, len(entries)):
        prev_ts = entries[i - 1].get("ts")
        curr_ts = entries[i].get("ts")
        if prev_ts and curr_ts:
            if isinstance(prev_ts, str):
                prev_ts = datetime.fromisoformat(prev_ts)
            if isinstance(curr_ts, str):
                curr_ts = datetime.fromisoformat(curr_ts)
            gap_seconds = (curr_ts - prev_ts).total_seconds()
            if gap_seconds > GAP_THRESHOLD_SECONDS:
                sampled_indices.add(i - 1)
                sampled_indices.add(i)

    # Ordenar índices y retornar los entries correspondientes
    sorted_indices = sorted(sampled_indices)
    return [entries[i] for i in sorted_indices]

# Cargar datos del archivo
full_history = []
with open('/home/mtrapaglia/projects/status_page/pi_history_full.jsonl', 'r') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            full_history.append(json.loads(line))
        except:
            pass

print(f"Total puntos en archivo: {len(full_history)}")

# Buscar eventos críticos
offline_indices = [i for i, entry in enumerate(full_history) if entry.get('online') is False]
print(f"\nPuntos con online=false: {len(offline_indices)}")
for idx in offline_indices:
    print(f"  Índice {idx}: {full_history[idx]['ts']}")

# Probar el downsampling
max_points = 2000
downsampled = _downsample_entries(full_history, max_points)
downsampled_dict = {full_history.index(entry): entry for entry in downsampled}

print(f"\nResultado del downsampling mejorado:")
print(f"  Puntos totales: {len(downsampled)}")
print(f"  Caídas incluidas: {sum(1 for entry in downsampled if entry.get('online') is False)}")

for idx in offline_indices:
    if idx in downsampled_dict or full_history[idx] in downsampled:
        print(f"  ✓ Índice {idx} (caída) está incluido")
    else:
        print(f"  ✗ Índice {idx} (caída) NO está incluido")

# Contar gaps grandes
gap_count = 0
for i in range(1, len(downsampled)):
    prev_ts = datetime.fromisoformat(downsampled[i-1]['ts'])
    curr_ts = datetime.fromisoformat(downsampled[i]['ts'])
    gap = (curr_ts - prev_ts).total_seconds()
    if gap > 150:
        gap_count += 1
        print(f"  Gap de {gap/60:.1f} min entre {downsampled[i-1]['ts']} y {downsampled[i]['ts']}")

print(f"\nGaps grandes detectados en resultado: {gap_count}")
