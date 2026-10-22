"""Generate a static architecture graph and function inventory for pdfexact."""
from __future__ import annotations

import ast
import csv
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pdfexact"
OUT = ROOT / "results"


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return None


def clean_doc(node: ast.AST, fallback: str) -> str:
    doc = ast.get_docstring(node, clean=True) or ""
    line = next((line.strip() for line in doc.splitlines() if line.strip()), "")
    return line or fallback


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        return ast.unparse(node.args) + (f" -> {ast.unparse(node.returns)}" if node.returns else "")
    except Exception:
        return "(...)"


def function_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
    names = [arg.arg for arg in args]
    if node.args.vararg:
        names.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        names.append("**" + node.args.kwarg.arg)
    return names


def return_summary(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    annotation = ast.unparse(node.returns) if node.returns else "non annoté"
    values: list[str] = []
    for item in ast.walk(node):
        if isinstance(item, ast.Return) and item.value is not None:
            try:
                values.append(ast.unparse(item.value)[:100])
            except Exception:
                pass
    if not values:
        return annotation
    unique = list(dict.fromkeys(values))[:3]
    return f"{annotation}; valeurs observées: " + " | ".join(unique)


def is_internal_module(name: str | None) -> bool:
    return bool(name and (name == "pdfexact" or name.startswith("pdfexact.")))


def resolve_imported(name: str, imports: dict[str, str], functions: dict[str, dict]) -> str | None:
    if name in imports:
        candidate = imports[name]
        if candidate in functions:
            return candidate
        prefix, _, attr = candidate.rpartition(".")
        if prefix:
            target = f"{prefix}:{attr}"
            if target in functions:
                return target
    if name in functions:
        return name
    return None


def main() -> None:
    files = sorted(SOURCE.rglob("*.py"))
    modules: dict[str, dict] = {}
    functions: dict[str, dict] = {}
    module_imports: dict[str, dict[str, str]] = defaultdict(dict)
    module_calls: dict[str, set[str]] = defaultdict(set)
    function_nodes: dict[str, ast.AST] = {}

    for path in files:
        mod = module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules[mod] = {
            "id": mod,
            "file": str(path.relative_to(ROOT)),
            "description": clean_doc(tree, f"Module {mod}"),
            "lines": len(path.read_text(encoding="utf-8").splitlines()),
        }
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                for alias in item.names:
                    root = alias.asname or alias.name.split(".")[0]
                    module_imports[mod][root] = alias.name
            elif isinstance(item, ast.ImportFrom):
                base = item.module or ""
                if item.level:
                    base_parts = mod.split(".")[:-item.level]
                    base = ".".join(base_parts + ([base] if base else []))
                for alias in item.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    module_imports[mod][local] = f"{base}.{alias.name}" if base else alias.name

        def visit_defs(body: list[ast.stmt], prefix: str = "") -> None:
            for item in body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if isinstance(item, ast.ClassDef):
                        visit_defs(item.body, f"{prefix}{item.name}.")
                    continue
                qname = f"{mod}:{prefix}{item.name}"
                functions[qname] = {
                    "id": qname,
                    "module": mod,
                    "qualname": f"{prefix}{item.name}",
                    "file": str(path.relative_to(ROOT)),
                    "line": item.lineno,
                    "end_line": getattr(item, "end_lineno", item.lineno),
                    "kind": "method" if "." in prefix else "function",
                    "description": clean_doc(item, f"Fonction {prefix}{item.name}"),
                    "takes": function_parameters(item),
                    "signature": signature(item),
                    "returns": return_summary(item),
                    "receives_from": [],
                    "transmits_to": [],
                }
                function_nodes[qname] = item
                visit_defs(item.body, f"{prefix}{item.name}.")

        visit_defs(tree.body)

    by_module_name: dict[str, list[str]] = defaultdict(list)
    by_short_name: dict[str, list[str]] = defaultdict(list)
    for fid, data in functions.items():
        by_module_name[data["module"]].append(fid)
        by_short_name[data["qualname"].split(".")[-1]].append(fid)

    def resolve_call(mod: str, owner: str, call: ast.Call) -> str | None:
        name = dotted_name(call.func)
        if not name:
            return None
        local_functions = {fid: data for fid, data in functions.items() if data["module"] == mod}
        if name.startswith("self."):
            method = name.split(".", 1)[1]
            cls = owner.split(".")[0] if owner else ""
            candidate = f"{mod}:{cls}.{method}"
            return candidate if candidate in functions else None
        direct = f"{mod}:{name}"
        if direct in functions:
            return direct
        imported = module_imports[mod]
        if name in imported:
            target = imported[name]
            if target in modules:
                return None
            base, _, attr = target.rpartition(".")
            candidate = f"{base}:{attr}"
            if candidate in functions:
                return candidate
        root, _, attr = name.partition(".")
        imported_module = imported.get(root)
        if imported_module and is_internal_module(imported_module):
            candidate = f"{imported_module}:{attr}"
            if candidate in functions:
                return candidate
        candidates = by_short_name.get(name, [])
        if len(candidates) == 1:
            return candidates[0]
        return None

    for fid, node in function_nodes.items():
        mod = functions[fid]["module"]
        owner = functions[fid]["qualname"]
        for item in ast.walk(node):
            if not isinstance(item, ast.Call):
                continue
            target = resolve_call(mod, owner, item)
            if target and target != fid:
                module_calls[fid].add(target)

    # Add module-level dependency edges from internal imports and function calls.
    imports_edges: set[tuple[str, str]] = set()
    for mod, imports in module_imports.items():
        for imported in imports.values():
            if is_internal_module(imported):
                target = imported if imported in modules else imported.rpartition(".")[0]
                if target in modules and target != mod:
                    imports_edges.add((mod, target))
    calls_edges = sorted((src, dst) for src, targets in module_calls.items() for dst in targets)
    for src, dst in calls_edges:
        functions[src]["transmits_to"].append(dst)
        functions[dst]["receives_from"].append(src)
    for data in functions.values():
        data["transmits_to"].sort()
        data["receives_from"].sort()

    graph = {
        "project": "pdfexact",
        "generated_from": "pdfexact/**/*.py",
        "modules": sorted(modules.values(), key=lambda x: x["id"]),
        "functions": sorted(functions.values(), key=lambda x: (x["module"], x["line"], x["qualname"])),
        "edges": {
            "imports": [{"from": a, "to": b} for a, b in sorted(imports_edges)],
            "calls": [{"from": a, "to": b} for a, b in calls_edges],
        },
        "notes": [
            "Call edges are static AST-resolved edges; dynamic getattr/import/plugin calls may be absent.",
            "Return values are inferred from annotations and literal return expressions where available.",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "architecture_graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

    with (OUT / "architecture_functions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["module", "fonction", "fichier", "ligne", "description", "prend_en_entree", "retourne", "recoit_de", "transmet_a"])
        for item in graph["functions"]:
            writer.writerow([
                item["module"], item["qualname"], f"{item['file']}:{item['line']}", item["line"], item["description"],
                "; ".join(item["takes"]), item["returns"], "; ".join(item["receives_from"]), "; ".join(item["transmits_to"]),
            ])

    lines = [
        "# Graphe d'architecture de pdfexact",
        "",
        f"Inventaire statique de **{len(graph['modules'])} modules** et **{len(graph['functions'])} fonctions/méthodes**.",
        "Les relations d'appel sont résolues par AST ; les appels dynamiques peuvent ne pas être détectés.",
        "",
        "## Pipeline principal",
        "",
        "```mermaid",
        "flowchart LR",
        "  CLI[pdfexact.cli] --> FONTS[fontlib / extract.fonts]",
        "  CLI --> EXTRACT[extract.document.extraire]",
        "  EXTRACT --> LAYOUT[layout.ai + layout.planner + layout.analyzer]",
        "  EXTRACT --> TEXT[extract.text / extract.ocr]",
        "  EXTRACT --> VIS[extract.images / vector / tables / rasterize]",
        "  EXTRACT --> IR[ir.Document / Page / TextBox / RasterEl]",
        "  IR --> NATIVE[render.native_contract]",
        "  IR --> WRITER[render.docx_writer / render.drawing / render.package]",
        "  WRITER --> DOCX[DOCX Word natif]",
        "  DOCX --> AUDIT[final_audit + report]",
        "  AUDIT --> DOCX",
        "```",
        "",
        "## Graphe complet",
        "",
        "Le graphe détaillé fonction-par-fonction est fourni dans `architecture_graph.json` et `architecture_graph.dot`.",
        "Le JSON contient les nœuds modules/fonctions et les arêtes `imports`/`calls`.",
        "",
        "## Dépendances entre modules",
        "",
        "```mermaid",
        "flowchart TD",
    ]
    for src, dst in sorted(imports_edges):
        lines.append(f"  {src.replace('.', '_')}[{src}] --> {dst.replace('.', '_')}[{dst}]")
    lines += ["```", "", "## Tableau exhaustif des fonctions", ""]
    lines.append("| Module | Fonction | Fichier:ligne | Description | Prend en entrée | Retourne | Reçoit de | Transmet à |")
    lines.append("|---|---|---:|---|---|---|---|---|")
    for item in graph["functions"]:
        def cell(value: str) -> str:
            return re.sub(r"\s+", " ", str(value)).replace("|", "\\|").strip()
        lines.append("| " + " | ".join([
            cell(item["module"]), cell(item["qualname"]), cell(f"{item['file']}:{item['line']}"),
            cell(item["description"]), cell(item["signature"]), cell(item["returns"]),
            cell(", ".join(item["receives_from"])), cell(", ".join(item["transmits_to"])),
        ]) + " |")
    (OUT / "architecture_graph.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    dot = ["digraph pdfexact {", "  rankdir=LR;", "  graph [fontname=Arial];", "  node [shape=box, fontname=Arial, fontsize=8];"]
    for mod in sorted(modules):
        safe_mod = re.sub(r"[^A-Za-z0-9_]", "_", mod)
        dot.append(f'  subgraph "cluster_{safe_mod}" {{ label="{mod}"; color="#cccccc"; }}')
    for item in graph["functions"]:
        node = re.sub(r"[^A-Za-z0-9_]", "_", item["id"])
        label = f"{item['module']}:{item['qualname']}\\nL{item['line']}"
        dot.append(f'  {node} [label="{label}"];')
    for src, dst in calls_edges:
        dot.append(f"  {re.sub(r'[^A-Za-z0-9_]', '_', src)} -> {re.sub(r'[^A-Za-z0-9_]', '_', dst)};")
    dot.append("}")
    (OUT / "architecture_graph.dot").write_text("\n".join(dot) + "\n", encoding="utf-8")
    print(json.dumps({"modules": len(modules), "functions": len(functions), "imports": len(imports_edges), "calls": len(calls_edges)}))


if __name__ == "__main__":
    main()
