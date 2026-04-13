#!/usr/bin/env python3
"""Test que el API devuelve overlays correctamente"""

import requests
import json

url = 'http://localhost:80/api/prices?token=gaelito2025'

try:
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    pi_history = data.get('pi_history_full', {})
    overlays = pi_history.get('overlays')

    print("=== RESULTADO DEL API ===")
    print(f"pi_history_full presente: {pi_history is not None}")
    print(f"overlays presente: {overlays is not None}")

    if overlays:
        print(f"\nofflineSpans: {len(overlays.get('offlineSpans', []))} spans")
        for span in overlays.get('offlineSpans', []):
            print(f"  {span}")

        print(f"\npowerSpans: {len(overlays.get('powerSpans', []))} spans")
        for span in overlays.get('powerSpans', []):
            print(f"  {span}")
    else:
        print("\n⚠️  No se encontraron overlays en la respuesta")
        print(f"\nClaves en pi_history_full: {list(pi_history.keys())}")

except Exception as e:
    print(f"Error: {e}")
