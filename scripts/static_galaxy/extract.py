#!/usr/bin/env python3
"""Static-Galaxy extractor (MVP)

Scans a repo for Python files and emits a simple graph JSON with:
- classes, methods, attributes
- method calls (best-effort)
- attribute usages

Usage:
  python scripts/static_galaxy/extract.py ~/projects/status_page -o out/graph.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tree_sitter import Language, Parser
import tree_sitter_python as tspython

# ---------- helpers ----------

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def walk_py_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*.py") if "venv" not in p.parts and ".venv" not in p.parts and "__pycache__" not in p.parts]


def node_text(src: str, node) -> str:
    return src[node.start_byte:node.end_byte]


# ---------- graph structures ----------

class Graph:
    def __init__(self) -> None:
        self.nodes: Dict[str, dict] = {}
        self.edges: List[dict] = []

    def add_node(self, node_id: str, **attrs):
        if node_id not in self.nodes:
            self.nodes[node_id] = {"id": node_id, **attrs}
        else:
            self.nodes[node_id].update(attrs)

    def add_edge(self, source: str, target: str, type_: str):
        self.edges.append({"source": source, "target": target, "type": type_})

    def to_json(self) -> dict:
        return {"nodes": list(self.nodes.values()), "edges": self.edges}


# ---------- parsing ----------

PY_LANGUAGE = Language(tspython.language())
parser = Parser()
parser.language = PY_LANGUAGE


def extract_from_file(path: Path, graph: Graph, repo_root: Path):
    src = read_text(path)
    tree = parser.parse(bytes(src, "utf8"))
    root = tree.root_node
    rel_path = str(path.relative_to(repo_root))

    # Map class name -> node + attributes / methods
    def walk(node, current_class: Optional[str] = None):
        # class definition
        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            class_name = node_text(src, name_node)
            class_id = f"class:{class_name}"

            # loc (line count) for class: rough estimate via span
            loc = node.end_point[0] - node.start_point[0] + 1
            graph.add_node(class_id, type="class", name=class_name, loc=loc, path=rel_path)

            # inheritance (best-effort)
            bases = node.child_by_field_name("superclasses")
            if bases:
                for child in bases.named_children:
                    base_name = node_text(src, child)
                    base_id = f"class:{base_name}"
                    graph.add_node(base_id, type="class", name=base_name)
                    graph.add_edge(class_id, base_id, "inherits")

            # walk body with class context
            body = node.child_by_field_name("body")
            if body:
                for c in body.named_children:
                    walk(c, current_class=class_name)
            return

        # function / method
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            func_name = node_text(src, name_node)
            if current_class:
                method_id = f"method:{current_class}.{func_name}"
                graph.add_node(method_id, type="method", name=func_name, class_name=current_class, path=rel_path)
                graph.add_edge(f"class:{current_class}", method_id, "has_method")
            else:
                method_id = f"function:{func_name}"
                graph.add_node(method_id, type="function", name=func_name, path=rel_path)

            # scan inside for calls / attribute usage
            body = node.child_by_field_name("body")
            if body:
                scan_calls_and_attrs(body, src, graph, current_class, method_id, rel_path)
            return

        # assignments to self.attr inside class body
        if node.type == "assignment" and current_class:
            # Look for "self.<attr> = ..."
            left = node.child_by_field_name("left")
            if left and left.type == "attribute":
                attr = node.child_by_field_name("left")
                attr_text = node_text(src, attr)
                if attr_text.startswith("self."):
                    attr_name = attr_text.split(".", 1)[1]
                    attr_id = f"attr:{current_class}.{attr_name}"
                    graph.add_node(attr_id, type="attr", name=attr_name, class_name=current_class, usages=0, path=rel_path)
                    graph.add_edge(f"class:{current_class}", attr_id, "has_attr")

        # recurse
        for c in node.named_children:
            walk(c, current_class=current_class)

    walk(root)


def scan_calls_and_attrs(node, src: str, graph: Graph, current_class: Optional[str], method_id: str, rel_path: str):
    def walk(n):
        # calls
        if n.type == "call":
            func_node = n.child_by_field_name("function")
            if func_node:
                callee = node_text(src, func_node)
                target_id = f"method:{callee}"
                graph.add_node(target_id, type="method", name=callee, path=rel_path)
                graph.add_edge(method_id, target_id, "calls")

        # attribute usage (self.attr)
        if n.type == "attribute" and current_class:
            text = node_text(src, n)
            if text.startswith("self."):
                attr_name = text.split(".", 1)[1]
                attr_id = f"attr:{current_class}.{attr_name}"
                graph.add_node(attr_id, type="attr", name=attr_name, class_name=current_class, usages=0, path=rel_path)
                # increment usage count
                graph.nodes[attr_id]["usages"] = graph.nodes[attr_id].get("usages", 0) + 1
                graph.add_edge(method_id, attr_id, "uses")

        for c in n.named_children:
            walk(c)

    walk(node)


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="Path to repo")
    ap.add_argument("-o", "--out", default="out/graph.json", help="Output JSON path")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    graph = Graph()
    for pyfile in walk_py_files(repo):
        extract_from_file(pyfile, graph, repo)

    out.write_text(json.dumps(graph.to_json(), indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
