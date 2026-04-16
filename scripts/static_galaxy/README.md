# Static-Galaxy extractor (MVP)

Genera un grafo JSON desde un repo Python usando Tree-sitter.

## Requisitos
- `tree_sitter`
- `tree_sitter_python`

Instalación rápida:
```bash
pip install tree_sitter tree_sitter_python
```

## Uso
```bash
python scripts/static_galaxy/extract.py ~/projects/status_page -o out/graph.json
```

## Salida
`out/graph.json` con nodos (`class`, `method`, `function`, `attr`) y relaciones (`inherits`, `has_method`, `has_attr`, `calls`, `uses`).

## Notas
- MVP: las llamadas se resuelven por texto (best-effort), no hay resolución semántica completa.
- Se ignoran `venv`, `.venv`, `__pycache__`.
