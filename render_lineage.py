#!/usr/bin/env python3
"""Draw any dbt project's lineage page from its manifest: one self-contained HTML file.

Carved out of Calon Analytics' Backbone lineage page. Every model, seed, snapshot and
source by layer; what each model computes (its authored description first, then a
summary parsed from the SQL: header comment, derived columns, filters, CTE steps);
which tests guard it; and a filter by source system.

Usage::

    render_lineage.py render --project DIR --out FILE [--manifest PATH] [--config PATH]
    render_lineage.py record --project DIR --url URL --sha256 HEX [--extra JSON]

``render`` prints ONE JSON line and exits 0 rendered, 2 usage, 3 no manifest,
4 too large, 5 invalid. ``unchanged`` is true when the page's sha256 equals the one
recorded in ``{project}/.dbt-lineage.json`` (written by ``record`` after a publish).

Stdlib only. PyYAML (which every dbt install has) is needed only when a
``lineage.yml`` config exists. Reads the manifest and the config; writes ``--out``
(render) or the record file (record). No dbt, no warehouse.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
RECORD_FILE = ".dbt-lineage.json"
CONFIG_FILES = ("lineage.yml", "lineage.yaml")

#: Leaves headroom under the 16 MB artifact limit.
MAX_BYTES = 15_000_000
MAX_NODES = 50_000
MAX_SINGULAR_DETAIL = 500
MAX_DERIVATIONS = 80
MAX_FILTERS = 20
MAX_CTES = 30
MAX_HEADER_PARAS = 14
MAX_STALE_FILES = 20_000
OTHER_SOURCES = "Other sources"
TITLE_SUFFIX = "dbt lineage"
EXIT_USAGE, EXIT_NO_MANIFEST, EXIT_TOO_LARGE, EXIT_INVALID = 2, 3, 4, 5

#: Default layers, left to right: (id, label). Override with ``layers:`` in lineage.yml.
DEFAULT_LAYERS: Tuple[Tuple[str, str], ...] = (
    ("source", "Sources"), ("snapshots", "Snapshots"), ("staging", "Staging"),
    ("intermediate", "Intermediate"), ("marts", "Marts"), ("reporting", "Reporting"),
    ("other", "Other"),
)
#: Default model rules: (kind, label, layer, dbt tags, name prefixes, folders).
#: Matching runs in three passes: every rule's tags, then every rule's name prefixes,
#: then every rule's folders (any directory on the path under models/). The first rule
#: to match in the earliest pass wins. Override with ``rules:`` in lineage.yml.
Rule = Tuple[str, str, str, Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]
DEFAULT_RULES: Tuple[Rule, ...] = (
    ("base", "Base models (base_)", "staging", ("base",), ("base_",), ("base",)),
    ("stg", "Staging models (stg_)", "staging", ("staging", "stg"), ("stg_",),
     ("staging", "stage", "stg")),
    ("int", "Intermediate models (int_)", "intermediate", ("intermediate", "int"),
     ("int_",), ("intermediate", "int")),
    ("fct", "Facts (fct_)", "marts", ("fact", "facts", "fct"), ("fct_", "fact_"), ()),
    ("dim", "Dimensions (dim_)", "marts", ("dimension", "dimensions", "dim"), ("dim_",),
     ()),
    ("mart", "Mart models", "marts", ("marts", "mart"), ("mart_",),
     ("marts", "mart", "core")),
    ("rpt", "Reports (rpt_)", "reporting", ("reporting", "report", "reports"),
     ("rpt_", "report_"), ("reporting", "reports", "report")),
)
FIXED_KINDS = (("source", "Source tables"), ("seed", "Seeds"), ("snapshot", "Snapshots"))
OTHER_KIND = ("model", "Other models")

NODE_TYPES = frozenset({"model", "seed", "snapshot", "source"})
_SCRIPT_SAFE = {ord("<"): "\\u003c", ord(">"): "\\u003e", ord("&"): "\\u0026",
                0x2028: "\\u2028", 0x2029: "\\u2029"}


class Invalid(Exception):
    """A manifest or config the page cannot be drawn from (exit 5)."""


class TooLarge(Exception):
    def __init__(self, byte_size: int):
        super().__init__(byte_size)
        self.byte_size = byte_size


# --- config ---------------------------------------------------------------------------


def load_config(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        import yaml  # dbt depends on PyYAML
    except ImportError as exc:
        raise Invalid(f"{path.name} needs PyYAML to read") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise Invalid(f"{path.name} must be a mapping")
    unknown = set(data) - {"title", "partition_name", "partitions", "layers", "rules",
                           "shared_kinds"}
    if unknown:
        raise Invalid(f"{path.name}: unknown keys {sorted(unknown)}")
    return data


class Scheme:
    """Layers, kinds and classification rules: the defaults, or the config's."""

    def __init__(self, config: Mapping[str, Any]):
        layers = config.get("layers")
        self.layers: List[Tuple[str, str]] = (
            [(str(x["id"]), str(x.get("label") or x["id"])) for x in layers]
            if layers else list(DEFAULT_LAYERS))
        ids = [layer for layer, _ in self.layers]
        for needed in ("source", "other"):
            if needed not in ids:
                self.layers.insert(0 if needed == "source" else len(self.layers),
                                   (needed, needed.title()))
        rules = config.get("rules")
        self.rules: List[Rule] = (
            [_parse_rule(i, r) for i, r in enumerate(rules)] if rules
            else list(DEFAULT_RULES))
        layer_ids = {layer for layer, _ in self.layers}
        for kind, _label, layer, *_matchers in self.rules:
            if layer not in layer_ids:
                raise Invalid(f"rule {kind!r} names layer {layer!r}, not in layers")
        self.snapshot_layer = "snapshots" if "snapshots" in layer_ids else "source"
        self.kinds: List[Tuple[str, str]] = list(FIXED_KINDS[:2]) + [FIXED_KINDS[2]]
        for kind, label, *_ in self.rules:
            if kind not in dict(self.kinds):
                self.kinds.append((kind, label))
        self.kinds.append(OTHER_KIND)
        self.shared_kinds = frozenset(config.get("shared_kinds") or ())
        self.layer_index = {layer: i for i, (layer, _) in enumerate(self.layers)}
        self.kind_index = {kind: i for i, (kind, _) in enumerate(self.kinds)}

    def classify(self, resource: Mapping[str, Any]) -> Tuple[str, str]:
        rtype = resource.get("resource_type")
        if rtype == "source":
            return "source", "source"
        if rtype == "seed":
            return "seed", "source"
        if rtype == "snapshot":
            return "snapshot", self.snapshot_layer
        tags = {str(t).lower() for t in resource.get("tags") or ()}
        name = (resource.get("name") or "").lower()
        folders = {p.lower() for p in (resource.get("original_file_path") or "")
                   .split("/")[1:-1]}
        passes = (
            lambda rule: bool(tags & set(rule[3])),
            lambda rule: any(name.startswith(p) for p in rule[4]),
            lambda rule: bool(folders & set(rule[5])),
        )
        for matches in passes:
            for rule in self.rules:
                if matches(rule):
                    return rule[0], rule[2]
        return OTHER_KIND[0], "other"


_RULE_KEYS = frozenset({"kind", "label", "layer", "tags", "prefixes", "folders"})


def _parse_rule(index: int, raw: Any) -> Rule:
    """One ``rules:`` entry; matchers are lower-cased, a bare string is a one-item list."""
    if not isinstance(raw, dict) or not raw.get("kind") or not raw.get("layer"):
        raise Invalid(f"rules[{index}] needs a kind and a layer")
    unknown = set(raw) - _RULE_KEYS
    if unknown:
        raise Invalid(f"rules[{index}]: unknown keys {sorted(unknown)}")

    def strings(key: str) -> Tuple[str, ...]:
        value = raw.get(key) or ()
        return tuple(str(v).lower() for v in ([value] if isinstance(value, str) else value))

    return (str(raw["kind"]), str(raw.get("label") or raw["kind"]), str(raw["layer"]),
            strings("tags"), strings("prefixes"), strings("folders"))


# --- the Logic tab (plain SQL) --------------------------------------------------------

_CONFIG_BLOCK = re.compile(r"^\s*\{\{.*?\}\}\s*", re.S)
_SKIP_LINE = re.compile(r"^(\w+\.sql$|Generated at)")
_GEN_LINE = re.compile(r"^(Generated (by|from))")
_TRAILING_COMMENT = re.compile(r"\s+--.*$")
_IDENT = re.compile(r'^(?:\w+\.)?"?(\w+)"?$')
_ALIAS = re.compile(r"^\w+$")
_NOT_AN_EXPR = ("SELECT", "WITH", "FROM", "JOIN", "LEFT", "INNER")
_FILTER_START = re.compile(r"^(WHERE|QUALIFY|HAVING)\b", re.I)
_FILTER_CONT = re.compile(r"^(AND|OR)\b", re.I)
_CTE = re.compile(r"(?:^|,|WITH)\s*\n?\s*(\w+)\s+AS\s*\(", re.I | re.M)
_REF = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")


def table_section(title: str, cols: Sequence[str], rows: Iterable[Sequence[Any]],
                  note: Optional[str] = None) -> Dict[str, Any]:
    return {"t": "table", "title": title, "cols": list(cols),
            "rows": [["" if c is None else str(c) for c in row] for row in rows],
            "note": note}


def list_section(title: str, items: Iterable[Any], note: Optional[str] = None):
    return {"t": "list", "title": title, "items": [str(i) for i in items], "note": note}


def _comment_lines(text: str) -> List[str]:
    lines: List[str] = []
    for line in text.lstrip().splitlines():
        stripped = line.strip()
        if not stripped.startswith("--"):
            break
        lines.append(stripped[2:].strip())
    return lines


def _paragraphs(lines: Sequence[str]) -> Tuple[List[str], List[str]]:
    paragraphs: List[str] = []
    generator: List[str] = []
    current: List[str] = []
    for text in lines:
        if _SKIP_LINE.match(text):
            continue
        if text and not _GEN_LINE.match(text):
            current.append(text)
            continue
        if current:
            paragraphs.append(" ".join(current))
            current = []
        if text:
            generator.append(text)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs[:MAX_HEADER_PARAS], generator


def header(code: str) -> Tuple[List[str], List[str]]:
    """The model's leading ``--`` comment block; a config block may precede it."""
    for text in (code or "", _CONFIG_BLOCK.sub("", code or "", count=1)):
        paragraphs, generator = _paragraphs(_comment_lines(text))
        if paragraphs or generator:
            return paragraphs, generator
    return [], []


def _select_item(line: str) -> Tuple[str, str]:
    item = _TRAILING_COMMENT.sub("", line).strip().lstrip(",").rstrip(",").strip()
    if not item or item.startswith(("{{", "{%", "--")) or " AS " not in item.upper():
        return "", ""
    cut = item.upper().rfind(" AS ")
    expr, alias = item[:cut].strip(), item[cut + 4:].strip().strip('"')
    if not _ALIAS.match(alias) or expr.upper().startswith(_NOT_AN_EXPR):
        return "", ""
    return expr, alias


def _is_derivation(expr: str, alias: str) -> bool:
    if not expr or expr.endswith("(") or expr.count("(") != expr.count(")"):
        return False
    bare = _IDENT.match(expr)
    return not (bare and bare.group(1).lower() == alias.lower())


def derivations(code: str) -> Tuple[List[List[str]], int]:
    rows: List[List[str]] = []
    seen = set()
    for line in code.splitlines():
        expr, alias = _select_item(line)
        if not _is_derivation(expr, alias) or (alias, expr) in seen:
            continue
        seen.add((alias, expr))
        rows.append([alias, expr])
    return rows[:MAX_DERIVATIONS], len(rows)


def filters(code: str) -> List[str]:
    found: List[str] = []
    clause: List[str] = []
    for line in code.splitlines() + [""]:
        stripped = line.strip()
        if clause and _FILTER_CONT.match(stripped):
            clause.append(stripped)
            continue
        if clause and " ".join(clause) not in found:
            found.append(" ".join(clause))
        clause = [stripped] if _FILTER_START.match(stripped) else []
    return found[:MAX_FILTERS]


def ctes(code: str) -> List[str]:
    return [c for c in _CTE.findall(code) if c.upper() not in ("SELECT", "CAST")][:MAX_CTES]


def _sql_logic(code: str) -> Dict[str, Any]:
    sections: List[Dict[str, Any]] = []
    rows, total = derivations(code)
    if rows:
        note = f"First {len(rows)} of {total}" if total > len(rows) else None
        sections.append(table_section("Derived columns", ["Column", "Expression"], rows,
                                      note=note))
    found = filters(code)
    if found:
        sections.append(list_section("Filters", found))
    steps = ctes(code)
    if len(steps) > 1:
        sections.append(list_section("Steps (CTEs, in order)", steps))
    paragraphs, generator = header(code)
    return {"sum": paragraphs, "sec": sections, "gen": generator, "note": None}


def _authored(resource: Mapping[str, Any]) -> List[Dict[str, Any]]:
    columns = resource.get("columns") or {}
    described: List[List[str]] = []
    bare: List[str] = []
    for name in sorted(columns):
        text = str((columns[name] or {}).get("description") or "").strip()
        (described.append([name, text]) if text else bare.append(name))
    if not described:
        return []
    sections = [table_section("Columns", ["Column", "Description"], described)]
    if bare:
        sections.append(list_section(f"Columns without a description · {len(bare)}", bare))
    return sections


def summarise(resource: Mapping[str, Any], kind: str) -> Dict[str, Any]:
    if kind == "source":
        table = resource.get("identifier") or resource.get("name") or ""
        result = {"sum": [f"Loaded table {resource.get('database') or ''}."
                          f"{resource.get('schema') or ''}.{table}. dbt reads it; nothing "
                          "transforms it here."], "sec": [], "gen": [], "note": None}
    elif kind == "seed":
        result = {"sum": [f"Reference data loaded from "
                          f"{resource.get('original_file_path') or ''} by dbt seed."],
                  "sec": [], "gen": [], "note": None}
    else:
        result = _sql_logic(resource.get("raw_code") or "")
    lede = str(resource.get("description") or "").strip() or None
    authored = _authored(resource)
    has_code_logic = bool(result["sum"] or result["sec"])
    result.update(lede=lede, authored=authored,
                  code_heading="From the code" if (lede or authored) and has_code_logic
                  else None)
    return result


# --- graph ----------------------------------------------------------------------------


def _node(uid: str, resource: Mapping[str, Any], scheme: Scheme) -> Dict[str, Any]:
    kind, layer = scheme.classify(resource)
    is_source = resource.get("resource_type") == "source"
    name = resource.get("name") or uid
    node = {
        "uid": uid,
        "name": f"{resource.get('source_name')}.{name}" if is_source else name,
        "layer": layer, "kind": kind,
        "mat": (resource.get("config") or {}).get("materialized")
        or resource.get("resource_type"),
        "integration": kind in scheme.shared_kinds,
        "desc": resource.get("description") or "",
        "ncols": len(resource.get("columns") or {}),
        "path": resource.get("original_file_path") or "",
        "schema": resource.get("schema") or "",
        "code": resource.get("raw_code") or "",
    }
    if is_source:
        node["source_name"] = resource.get("source_name") or ""
    return node


def _resources(manifest: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {**(manifest.get("nodes") or {}), **(manifest.get("sources") or {})}


def parents_of(manifest: Mapping[str, Any], members: Iterable[str]) -> Dict[str, Tuple]:
    members = set(members)
    resources = manifest.get("nodes") or {}
    return {uid: tuple(sorted({p for p in ((resources.get(uid) or {}).get("depends_on")
                                           or {}).get("nodes") or [] if p in members}))
            for uid in members}


def _test_detail(name: str, kwargs: Mapping[str, Any]) -> str:
    if name == "relationships":
        to = str(kwargs.get("to") or "")
        found = _REF.search(to)
        return f"→ {found.group(1) if found else to}.{kwargs.get('field') or ''}"
    if name == "accepted_values":
        return ", ".join(str(v) for v in kwargs.get("values") or [])
    if name == "expression_is_true":
        return str(kwargs.get("expression") or "")
    if name == "unique_combination_of_columns":
        return ", ".join(str(c) for c in kwargs.get("combination_of_columns") or [])
    return ""


def _severity(test: Mapping[str, Any]) -> str:
    return str((test.get("config") or {}).get("severity") or "error").lower()


def _test_record(test: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    depends = list((test.get("depends_on") or {}).get("nodes") or [])
    metadata = test.get("test_metadata")
    if metadata:
        kwargs = metadata.get("kwargs") or {}
        name = metadata.get("name") or test.get("name") or ""
        record = {"n": name, "c": kwargs.get("column_name") or test.get("column_name") or "",
                  "d": _test_detail(name, kwargs), "s": _severity(test)}
        attached = test.get("attached_node")
        return record, [attached] if attached else depends
    name = test.get("name") or ""
    detail = " ".join(header(test.get("raw_code") or "")[0])
    if len(detail) > MAX_SINGULAR_DETAIL:
        detail = f"{detail[:MAX_SINGULAR_DETAIL]} (first {MAX_SINGULAR_DETAIL} characters)"
    record = {"n": name, "c": "", "d": detail, "s": _severity(test), "singular": True}
    named = [d for d in depends if d.split(".")[-1] in name]
    if named:
        longest = max(len(d.split(".")[-1]) for d in named)
        named = [d for d in named if len(d.split(".")[-1]) == longest]
    return record, named or depends


def attach_tests(manifest: Mapping[str, Any], uids: set) -> Dict[str, List[Dict]]:
    attached: Dict[str, List[Dict[str, Any]]] = {}
    resources = manifest.get("nodes") or {}
    for test_uid in sorted(resources):
        test = resources[test_uid]
        if test.get("resource_type") != "test":
            continue
        record, targets = _test_record(test)
        for target in sorted(set(targets)):
            if target in uids:
                attached.setdefault(target, []).append(dict(record))
    return attached


def _topological(parents: Mapping[str, Sequence[str]]) -> List[str]:
    if len(parents) > MAX_NODES:
        raise Invalid(f"manifest has {len(parents)} nodes, over the cap of {MAX_NODES}")
    pending = {uid: len(ps) for uid, ps in parents.items()}
    children: Dict[str, List[str]] = {uid: [] for uid in parents}
    for uid, ps in parents.items():
        for parent in ps:
            children[parent].append(uid)
    ready = sorted(uid for uid, count in pending.items() if count == 0)
    order: List[str] = []
    for _step in range(len(parents)):
        if not ready:
            break
        uid = ready.pop()
        order.append(uid)
        for child in children[uid]:
            pending[child] -= 1
            if pending[child] == 0:
                ready.append(child)
    if len(order) < len(parents):
        raise Invalid(f"cycle at {min(u for u, c in pending.items() if c > 0)}")
    return order


def source_systems(nodes: Mapping[str, Mapping], parents: Mapping[str, Sequence[str]],
                   shared: frozenset) -> Dict[str, Tuple[str, ...]]:
    """A source's system is its source_name; others inherit their parents' systems,
    except through a ``shared_kinds`` parent, which passes nothing on."""
    systems: Dict[str, Tuple[str, ...]] = {}
    for uid in _topological({uid: parents.get(uid, ()) for uid in nodes}):
        node = nodes[uid]
        if node["kind"] == "source":
            systems[uid] = (node.get("source_name") or "",)
            continue
        systems[uid] = tuple(sorted({s for p in parents.get(uid, ())
                                     if nodes[p]["kind"] not in shared
                                     for s in systems[p]}))
    return systems


def _partitions(config: Mapping[str, Any]) -> List[Tuple[str, Tuple[str, ...]]]:
    found = []
    for i, part in enumerate(config.get("partitions") or []):
        if not isinstance(part, dict) or not part.get("label"):
            raise Invalid(f"partitions[{i}] needs a label")
        found.append((str(part["label"]), tuple(str(s) for s in part.get("sources") or [])))
    return found


def assign_groups(systems: Mapping[str, Sequence[str]], config: Mapping[str, Any]):
    every = sorted({s for node_systems in systems.values() for s in node_systems})
    partitions = _partitions(config)
    if not partitions:
        return ({u: list(s) for u, s in systems.items()}, {u: [] for u in systems},
                every, "Sources", False, [])
    owner = {src.upper(): label for label, sources in partitions for src in sources}
    labels = [label for label, _ in partitions]
    groups = {}
    for uid, node_systems in systems.items():
        hit = {owner.get(s.upper(), OTHER_SOURCES) for s in node_systems}
        groups[uid] = [lb for lb in labels if lb in hit] + (
            [OTHER_SOURCES] if OTHER_SOURCES in hit else [])
    tags = {u: [g for g in gs if g != OTHER_SOURCES] for u, gs in groups.items()}
    filter_groups = labels + ([OTHER_SOURCES] if any(s.upper() not in owner
                                                     for s in every) else [])
    known = {s.upper() for s in every}
    warnings = [f"declared source {src} is not in the manifest"
                for _label, sources in partitions for src in sources
                if src.upper() not in known]
    return (groups, tags, filter_groups, str(config.get("partition_name") or "Partition"),
            True, warnings)


# --- page -----------------------------------------------------------------------------


def iso_utc(value: Any) -> str:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise Invalid(f"unparseable timestamp {value!r}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def stale_since(project: Path, generated_at: str) -> Optional[str]:
    """The newest model/seed/snapshot file time when it is after the manifest."""
    cutoff = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).timestamp()
    newest = 0.0
    seen = 0
    for folder in ("models", "seeds", "snapshots", "macros"):
        for path in (project / folder).rglob("*"):
            seen += 1
            if seen > MAX_STALE_FILES:
                break
            if path.suffix in (".sql", ".yml", ".yaml", ".csv", ".py"):
                newest = max(newest, path.stat().st_mtime)
    if newest <= cutoff:
        return None
    return datetime.fromtimestamp(newest, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_data(manifest: Mapping[str, Any], config: Mapping[str, Any], title: str,
               project: Path) -> Dict[str, Any]:
    metadata = manifest.get("metadata") or {}
    if not metadata.get("generated_at"):
        raise Invalid("manifest has no metadata.generated_at")
    scheme = Scheme(config)
    found = _resources(manifest)
    nodes = {uid: _node(uid, r, scheme) for uid, r in found.items()
             if r.get("resource_type") in NODE_TYPES}
    parents = parents_of(manifest, nodes)
    systems = source_systems(nodes, parents, scheme.shared_kinds)
    groups, tags, filter_groups, filter_name, declared, warnings = assign_groups(
        systems, config)
    tests = attach_tests(manifest, set(nodes))
    all_systems = sorted({n["source_name"] for n in nodes.values() if "source_name" in n})
    ordered = sorted(nodes.values(), key=lambda n: (
        scheme.layer_index.get(n["layer"], len(scheme.layers)),
        scheme.kind_index.get(n["kind"], len(scheme.kinds)), n["name"], n["uid"]))
    index = {n["uid"]: i for i, n in enumerate(ordered)}
    page_nodes = []
    for node in ordered:
        uid = node["uid"]
        node.pop("source_name", None)
        node.update(systems=list(systems[uid]), groups=groups[uid], tags=tags[uid],
                    tests=tests.get(uid, []))
        page_nodes.append({**node, **summarise(found[uid], node["kind"])})
    edges = sorted({(index[p], index[c]) for c, ps in parents.items() for p in ps})
    generated_at = iso_utc(metadata["generated_at"])
    stale = stale_since(project, generated_at)
    schema_url = str(metadata.get("dbt_schema_version") or "")
    return {
        "tid": manifest.get("metadata", {}).get("project_name") or project.name,
        "title": title, "generated_at": generated_at,
        "dbt_version": str(metadata.get("dbt_version") or ""),
        "schema_version": schema_url.rsplit("/", 1)[-1].split(".", 1)[0],
        "stale": {"build_started_at": stale} if stale else None, "size_tier": 1,
        "source_systems": all_systems, "filter_name": filter_name,
        "filter_groups": filter_groups, "partitions_declared": declared,
        "layers": [list(x) for x in scheme.layers],
        "layer_colour": {layer: min(i, 8) for i, (layer, _) in enumerate(scheme.layers)},
        "kinds": [list(x) for x in scheme.kinds],
        "nodes": page_nodes, "edges": [list(e) for e in edges],
        "_warnings": warnings,
    }


def _split_once(text: str, placeholder: str) -> Tuple[str, str]:
    parts = text.split(placeholder)
    if len(parts) != 2:
        raise RuntimeError(f"template must hold {placeholder} exactly once")
    return parts[0], parts[1]


def render(data: Mapping[str, Any], cap: int = MAX_BYTES) -> Tuple[str, str, int, int]:
    """``(html, sha256, byte_size, tier)``: tier 1 full, 2 drops staging/base code, 3
    drops all code."""
    head, rest = _split_once(TEMPLATE.read_text(encoding="utf-8"), "__TITLE__")
    mid, tail = _split_once(rest, "__DATA__")
    title = html.escape(f"{data['title']} · {TITLE_SUFFIX}")
    byte_size = 0
    for tier in (1, 2, 3):
        nodes = [{**n, "code": None if tier == 3 or (tier == 2 and n["layer"] in
                                                     ("staging", "snapshots"))
                  else n.get("code")} for n in data["nodes"]]
        payload = json.dumps({**data, "nodes": nodes, "size_tier": tier}, sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False)
        page = head + title + mid + payload.translate(_SCRIPT_SAFE) + tail
        encoded = page.encode("utf-8")
        byte_size = len(encoded)
        if byte_size <= cap:
            return page, hashlib.sha256(encoded).hexdigest(), byte_size, tier
    raise TooLarge(byte_size)


# --- CLI ------------------------------------------------------------------------------


def _emit(payload: Dict[str, Any], code: int) -> "NoReturn":  # noqa: F821
    print(json.dumps(payload, sort_keys=True))
    sys.exit(code)


def _read_record(project: Path) -> Optional[Dict[str, Any]]:
    path = project / RECORD_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ignoring unreadable {RECORD_FILE}: {exc}", file=sys.stderr)
        return None


def cmd_render(args: argparse.Namespace) -> None:
    project = Path(args.project).resolve()
    if not (project / "dbt_project.yml").exists():
        _emit({"status": "usage", "detail": f"no dbt_project.yml in {project}"}, EXIT_USAGE)
    manifest_path = Path(args.manifest) if args.manifest else project / "target/manifest.json"
    if not manifest_path.exists():
        _emit({"status": "no_manifest", "manifest": str(manifest_path)}, EXIT_NO_MANIFEST)
    config_path = Path(args.config) if args.config else next(
        (project / f for f in CONFIG_FILES if (project / f).exists()), None)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        config = load_config(config_path)
        title = str(config.get("title") or (manifest.get("metadata") or {}).get(
            "project_name") or project.name)
        data = build_data(manifest, config, title, project)
        warnings = data.pop("_warnings")
        page, sha, byte_size, tier = render(data)
    except (Invalid, ValueError, KeyError, TypeError) as exc:
        _emit({"status": "invalid", "detail": f"{type(exc).__name__}: {exc}"}, EXIT_INVALID)
    except TooLarge as exc:
        _emit({"status": "too_large", "byte_size": exc.byte_size}, EXIT_TOO_LARGE)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    record = _read_record(project)
    _emit({"status": "rendered", "out": str(out), "sha256": sha, "byte_size": byte_size,
           "size_tier": tier, "node_count": len(data["nodes"]),
           "edge_count": len(data["edges"]), "manifest_generated_at": data["generated_at"],
           "title": data["title"], "stale": data["stale"], "warnings": warnings,
           "config": str(config_path) if config_path else None,
           "artifact_url": (record or {}).get("artifact_url"),
           "unchanged": bool(record and record.get("html_sha256") == sha)}, 0)


def cmd_record(args: argparse.Namespace) -> None:
    project = Path(args.project).resolve()
    record = {"artifact_url": args.url, "html_sha256": args.sha256,
              "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    record.update(json.loads(args.extra) if args.extra else {})
    (project / RECORD_FILE).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _emit({"status": "recorded", "path": str(project / RECORD_FILE)}, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--project", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--manifest")
    r.add_argument("--config")
    r.set_defaults(func=cmd_render)
    c = sub.add_parser("record")
    c.add_argument("--project", required=True)
    c.add_argument("--url", required=True)
    c.add_argument("--sha256", required=True)
    c.add_argument("--extra")
    c.set_defaults(func=cmd_record)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
