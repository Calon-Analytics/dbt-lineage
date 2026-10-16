---
name: dbt-lineage
description: Draw any dbt project's lineage page from its target/manifest.json and publish it as a Claude artifact at one stable URL. One self-contained HTML page — every model, seed, snapshot and source by layer (sources → staging → intermediate → marts → reporting), what each model computes (authored descriptions first, then header comment, derived columns, filters and CTE steps parsed from the SQL), the tests that guard it, upstream/downstream tracing and a filter by source system. Republishes in place and skips when unchanged. Runs no dbt against the warehouse. Use when the user asks for a dbt lineage / DAG / dataflow page, diagram or artifact.
---

# dbt-lineage

Renders a dbt project's lineage page with the bundled `render_lineage.py` (stdlib
Python; PyYAML only if a `lineage.yml` exists) and `template.html`, then publishes the
file it wrote with the Artifact tool. Carved out of Calon Analytics' Backbone lineage page.

Invocation: `/dbt-lineage [project dir]`. Default: the nearest directory at or above
the working directory holding `dbt_project.yml`. If several sit below it, ask which.

`{skill}` is this skill's directory; `{scratchpad}` the session scratchpad.

## Steps

### 1. Render

```
python3 {skill}/render_lineage.py render --project {project} \
    --out {scratchpad}/lineage/{project name}-lineage.html
```

Optional: `--manifest PATH` (default `{project}/target/manifest.json`),
`--config PATH` (default `{project}/lineage.yml` if present).

It prints one JSON line: `status`, `out`, `sha256`, `byte_size`, `size_tier`,
`node_count`, `edge_count`, `manifest_generated_at`, `title`, `stale`, `warnings`,
`artifact_url` (recorded), `unchanged`.

| Exit | `status` | Then |
|---|---|---|
| 0 | `rendered` | continue |
| 3 | `no_manifest` | Offer `dbt parse` (writes the manifest; compiles nothing against the warehouse, but needs a working profile). Run it only on a yes, then render again. |
| 4 | `too_large` | Over 15 MB even with all code dropped. Stop. |
| 5 | `invalid` | Show `detail` verbatim. Stop. |
| 2 | `usage` | Show `detail` verbatim. Stop. |
| 1 | — | Crash: show the traceback's last line. Stop. |

Print each `warnings` entry. If `stale` is set, say model files changed after the
manifest and suggest `dbt parse` first (do not block).

### 2. Unchanged

`unchanged: true` → *"Lineage page unchanged (manifest {manifest_generated_at}):
{artifact_url}"*. Stop.

### 3. Publish

Description: *"dbt lineage for {title}, drawn from the manifest of
{manifest_generated_at}"*.

- **With `artifact_url`:** Artifact `action: "read"` on it with `prompt: "reply only with
  the writer status"` — do not print what it returns. Then publish `file_path` = `out`,
  `url` = `artifact_url`. If the read inlines the page anyway, skip it next time and
  publish directly; a refusal that hands back the live version counts as the read —
  publish this file again (never the version handed back).
- **Refused / not found / not editable:** publish a new artifact (`icon: "network"`) and
  note the link changed.
- **No `artifact_url`:** publish new with `icon: "network"`.
- **No Artifact tool:** report the rendered path and stop (no record).

### 4. Record

```
python3 {skill}/render_lineage.py record --project {project} --url {url} --sha256 {sha256}
```

Writes `{project}/.dbt-lineage.json`. Mention once that it can be committed (keeps the
URL for teammates) or gitignored.

### 5. Report

One line: *"Lineage page for {title} published: {url} ({node_count} nodes,
{edge_count} edges, manifest {manifest_generated_at}{, code omitted: tier N}{, stale})"*.
Artifacts start private: say the user shares it when they choose.

## Configuration (optional `lineage.yml` in the project root)

```yaml
title: Jaffle Shop              # default: the manifest's project_name
partition_name: Region          # filter by groups of sources instead of single sources
partitions:
  - label: EU
    sources: [shop_eu, erp_eu]  # dbt source names
layers:                         # left-to-right columns; source and other are always added
  - {id: source, label: Sources}
  - {id: staging, label: Staging}
  - {id: marts, label: Marts}
rules:                          # passes: dbt tags, then name prefix, then folder under models/
  - {kind: stg, label: "Staging (stg_)", layer: staging, tags: [staging], prefixes: [stg_], folders: [staging]}
  - {kind: fct, label: "Facts (fct_)", layer: marts, tags: [fact], prefixes: [fct_]}
shared_kinds: [dim]             # kinds that do not pass their source systems downstream
```

A model's column comes from its **dbt tags first**, then its name prefix, then its
folder; within a pass the first matching rule wins (case-insensitive). Defaults follow
dbt Labs' project-structure conventions: tag `staging`/`stg` or `base_`/`stg_` →
Staging, `intermediate`/`int_` → Intermediate, `fact`/`dim`/`marts` or
`fct_`/`dim_`/`mart_` or `models/marts` → Marts, `reporting` or `rpt_` → Reporting;
snapshots get their own column; anything unmatched → Other.

When a project marks layers with tags the defaults don't know (look at the manifest's
most common model tags), offer the user a `lineage.yml` with tag rules for them.

## Size tiers

Tier 1 includes all code; tier 2 drops staging/snapshot code; tier 3 drops all code (the
Logic summaries stay). The cap is 15 MB, under the 16 MB artifact limit.

## Out of scope

Column-level lineage; running `dbt build`/`run`; exposures, metrics and semantic models
(not drawn as nodes).
