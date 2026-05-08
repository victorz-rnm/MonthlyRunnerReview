# Runner Review Report Generator

This is the first automated version of the monthly / bi-weekly runner review flow. It runs parameterized KQL templates for a date range, caches the raw data as CSV, and creates a 16:9 PowerPoint deck designed for presentation slides.

## Setup

```powershell
& "../.venv/Scripts/python.exe" -m pip install -r requirements.txt
```

Run commands from the `report` folder, or pass paths explicitly from the workspace root.

## Generate a Deck

```powershell
& "../.venv/Scripts/python.exe" generate_runner_review.py --start 2026-04-15 --end 2026-04-30
```

By default, `--end` is inclusive. The command above queries `2026-04-15 00:00:00` through `2026-05-01 00:00:00`, writes CSV caches under `output/cache`, and writes the deck under `output`.

Useful options:

```powershell
& "../.venv/Scripts/python.exe" generate_runner_review.py --start 2026-04-15 --end 2026-04-30 --out output/runner-review.pptx
& "../.venv/Scripts/python.exe" generate_runner_review.py --start 2026-04-15 --end 2026-04-30 --use-cache
& "../.venv/Scripts/python.exe" generate_runner_review.py --start 2026-04-15 --end 2026-04-30 --query runner_sev2_detail --query dri_acknowledge_detail
& "../.venv/Scripts/python.exe" generate_runner_review.py --start 2026-04-15 --end 2026-04-30 --render-kql output/rendered-kql
```

## Authentication

The default Kusto auth mode is interactive login. If that is awkward in your shell, try Azure CLI auth after `az login`:

```powershell
& "../.venv/Scripts/python.exe" generate_runner_review.py --start 2026-04-15 --end 2026-04-30 --auth azcli
```

## Generate the Proactive Scan KPI HTML

This renders a sidebar-style HTML report, similar to the manually generated Runner KPI report, using `KPI/Analyze Runner Sev2/Proactive-KPI.kql` as the source query.

```powershell
& "../.venv/Scripts/python.exe" generate_proactive_scan_kpi.py --month 2026-04 --auth azcli --render-kql output/rendered-kql/proactive_scan_kpi.kql
```

The command writes the HTML to `output/proactive-scan-kpi-2026-04.html` and caches the query result under `output/cache`. Add `--use-cache` to regenerate the HTML without querying Kusto again.

## Generate the Auto-Triage KPI HTML

This renders the same sidebar-style KPI HTML using all three result sets from `KPI/Analyze Runner Sev2/auto_triage_kpi_complete - advance.kql`: `IncidentLevelKpi`, `TeamLevelKpi`, and `OverallKpi`.

```powershell
& "../.venv/Scripts/python.exe" generate_auto_triage_kpi.py --month 2026-04 --auth azcli --render-kql output/rendered-kql/auto_triage_kpi.kql
```

The command writes the HTML to `output/auto-triage-kpi-2026-04.html` and caches one CSV per result set under `output/cache`.

## Data Sources

The first version uses these canonical datasets:

- `runner_sev2_detail`: runner Sev2/Sev2.5 detail, parsing runner, region, instance, phase, RCA, repair items, downgrade type, and proactive/triage markers.
- `cri_outage_detail`: CRI and outage detail with TTx, RCA, category, repair items, and links.
- `livesite_detail`: LiveSite/outage detail by monitor/team with TTx, RCA, category, and repair items.
- `dri_acknowledge_detail`: DRI acknowledge events split into Runner, CRI, LiveSite, and NCPQuality-Proactive.
- `proactive_linkage_detail`: Runner proactive linkage result, counting linked and found-parent outcomes as succeeded, with failed, database-down, and not-linked outcomes kept separate.
- `oaas_human_touch`: optional NRP OaaS vs human touch data. It is disabled by default because the Geneva audit source only supports a short window.

## Slide Sections

The generated deck includes executive summary, CRI trend, LiveSites by monitor, DRI acknowledge trend and patterns, team comparison against the previous period, NRP/RNM/NSM deep dive, top issue groups, and Runner proactive linkage KPI.

## Iteration Notes

This version keeps the top-issue grouping deterministic: it normalizes incident titles by removing volatile counts, percentages, IDs, and region-like tokens, then groups by team and incident family. That is explainable in review meetings and can later be upgraded with RCA-based or embedding-based clustering.
