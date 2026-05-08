from __future__ import annotations

import argparse
import html
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import generate_runner_review as runner_report


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent
DEFAULT_KQL = WORKSPACE_ROOT / "KPI" / "Analyze Runner Sev2" / "Proactive-KPI.kql"
DEFAULT_CACHE_DIR = SCRIPT_DIR / "output" / "cache"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"

RESULT_ORDER = ["Completed", "Incompleted", "ProactiveFailed", "DatabaseDown", "NotLinked"]
SUCCESS_RESULTS = {"Completed", "Incompleted"}
FAILURE_RESULTS = {"ProactiveFailed", "DatabaseDown"}
RESULT_LABELS = {
    "Completed": "Linked",
    "Incompleted": "Found parent",
    "ProactiveFailed": "Failure - others",
    "DatabaseDown": "Failure - database down",
    "NotLinked": "Not linked",
}
RESULT_COLORS = {
    "Completed": "#2ea043",
    "Incompleted": "#0a7f72",
    "ProactiveFailed": "#cf222e",
    "DatabaseDown": "#6e7781",
    "NotLinked": "#a8a29e",
    "Unknown": "#8c959f",
}
EXPECTED_COLUMNS = [
    "RunnerIncidentId",
    "ChildIncidentLink",
    "RunnerTitle",
    "Severity",
    "OwningTeamName",
    "IsProactivelyLinked",
    "LinkResult",
    "LinkedDate",
    "EvidenceDate",
    "ProactiveParentIncidentId",
    "ProactiveIncidentLink",
    "ProactiveTitle",
    "HasExistingParent",
    "HasProactiveParent",
    "Status",
]

STYLE = """
* { box-sizing: border-box; }
body { margin: 0; font-family: 'Segoe UI', Aptos, system-ui, sans-serif; color: #1a1a1a; background: #f7f8fa; }
.layout { display: grid; grid-template-columns: 240px 1fr; min-height: 100vh; }
.sidebar { background: #0E2841; color: #fff; padding: 24px 16px; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
.sidebar h1 { font-size: 16px; margin: 0 0 8px; }
.sidebar .meta { font-size: 11px; opacity: .72; margin-bottom: 24px; line-height: 1.45; }
.sidebar a { display: block; color: #cfd9e2; padding: 8px 10px; text-decoration: none; border-radius: 4px; font-size: 13px; margin-bottom: 2px; }
.sidebar a:hover { background: #156082; color: #fff; }
.content { padding: 32px 48px; max-width: 1500px; }
h2 { color: #0E2841; border-bottom: 2px solid #156082; padding-bottom: 6px; margin-top: 32px; }
h3 { color: #156082; margin-top: 24px; }
h4 { color: #0E2841; margin: 18px 0 6px; }
p { font-size: 13px; color: #444; line-height: 1.45; }
.column-definitions { margin: 8px 0 12px; padding: 10px 12px; border: 1px solid #d0d7de; border-left: 4px solid #156082; background: #f6f8fa; font-size: 12px; color: #3b434b; }
.column-definitions .definition-title { font-weight: 700; color: #0E2841; margin-bottom: 6px; }
.column-definitions dl { display: grid; grid-template-columns: minmax(130px, 220px) 1fr; gap: 4px 12px; margin: 0; }
.column-definitions dt { font-weight: 700; color: #0E2841; }
.column-definitions dd { margin: 0; line-height: 1.35; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
th, td { border: 1px solid #e1e4e8; padding: 8px 12px; text-align: left; font-size: 13px; vertical-align: top; }
th { background: #f0f3f7; color: #0E2841; font-weight: 600; white-space: nowrap; }
td { word-break: normal; overflow-wrap: anywhere; }
td:first-child { white-space: nowrap; }
td:last-child { max-width: 680px; line-height: 1.4; word-break: break-word; }
tr:nth-child(even) td { background: #fafbfc; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
.metric-current { font-weight: 700; color: #0E2841; font-size: 14px; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; color: #fff; }
.badge.green { background: #2ea043; }
.badge.yellow { background: #d4a72c; }
.badge.red { background: #cf222e; }
.badge.gray { background: #6e7781; }
.notes { background: #fff8dc; border-left: 4px solid #d4a72c; padding: 12px 16px; margin: 24px 0; font-size: 13px; }
.notes ul { margin: 6px 0 0 0; padding-left: 20px; }
.kusto-footnote { font-size: 11px; color: #888; margin: 8px 0 24px 0; font-style: italic; }
.delta-cell { font-weight: 700; }
.chart-wrap { margin: 12px 0 22px; overflow-x: auto; }
svg.report-chart { background:#fff; border:1px solid #e1e4e8; border-radius:6px; max-width: 100%; height: auto; }
tr.result-completed td { background: #f0fdf4 !important; }
tr.result-incompleted td { background: #ecfdf3 !important; }
tr.result-proactivefailed td, tr.result-databasedown td { background: #fff1f0 !important; }
tr.result-notlinked td { background: #f5f5f5 !important; color: #6e7781; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { position: static; height: auto; }
  .content { padding: 24px 16px; }
  .column-definitions dl { grid-template-columns: 1fr; }
}
""".strip()


COLUMN_DEFINITIONS: dict[str, list[tuple[str, str]]] = {
    "overview": [
        ("KPI", "The proactive linkage metric being evaluated for the previous and current periods."),
        ("Target", "The expected threshold or preferred direction for the metric."),
        ("Previous", "Value from the previous comparison period."),
        ("Current", "Value from the current reporting period; highlighted for scan reading."),
        ("Delta", "Current value minus previous value. Rates are shown in percentage points."),
        ("Status", "Badge based on the target or preferred direction."),
    ],
    "summary": [
        ("Month", "The reporting period represented by the row."),
        ("Total CP", "Count of Control Path Runner Sev2/2.5 child incidents in the period."),
        ("Succeeded", "Linked plus found-parent rows. These are counted as proactive success."),
        ("Linked", "Rows with formal duplicate relationship evidence to a proactive parent incident."),
        ("Found parent", "Rows where proactive parent evidence was found in the child incident description, even if IcM blocked creating the formal child link."),
        ("Failure - others", "Rows whose Eureka proactive triage text reports a non-database proactive failure."),
        ("Failure - database down", "Rows whose proactive triage evidence indicates the Eureka database was down or unavailable."),
        ("Not linked", "Runner child incidents with no proactive parent evidence found."),
        ("Success %", "Succeeded divided by Total CP."),
        ("Scan attempt %", "Rows with any proactive result other than Not linked, divided by Total CP."),
    ],
    "parent_coverage": [
        ("Month", "The reporting period represented by the row."),
        ("Total CP", "Count of Control Path Runner Sev2/2.5 child incidents in the period."),
        ("Has existing parent", "Runner child incidents that already had any IcM parent incident."),
        ("Existing parent %", "Has existing parent divided by Total CP."),
        ("Has proactive parent", "Runner child incidents where the report found a proactive parent through relationship or description evidence."),
        ("Proactive parent %", "Has proactive parent divided by Total CP."),
    ],
    "teams": [
        ("Owning Team", "Owning team from the runner child incident or enriched proactive evidence."),
        ("Total", "Current-month runner child incidents owned by the team."),
        ("Succeeded", "Current-month linked plus found-parent rows for the team."),
        ("Failed", "Current-month failure - others plus failure - database down rows for the team."),
        ("Not linked", "Current-month runner child incidents for the team with no proactive parent evidence."),
        ("Success %", "Succeeded divided by Total for the team."),
        ("Sample IcM", "Up to three example runner child incidents from that team."),
    ],
    "parents": [
        ("Proactive Parent", "The proactive parent incident found through duplicate relationship or description evidence."),
        ("Result Mix", "Breakdown of linked and found-parent child rows under that proactive parent."),
        ("Children", "Number of current-month runner child incidents associated with the proactive parent."),
        ("Status", "Current IcM status of the proactive parent incident."),
        ("Sample Runner ICM", "Example runner child incidents grouped under that proactive parent."),
        ("Title", "Trimmed proactive parent incident title."),
    ],
    "details": [
        ("Result", "Actionable result category: failure - others, failure - database down, or not linked."),
        ("Runner ICM", "The runner child incident requiring follow-up."),
        ("Proactive Parent", "The proactive parent when one is known; blank means none was found."),
        ("Sev", "Severity of the runner child incident."),
        ("Date", "Evidence date when available; otherwise the runner child incident date."),
        ("Existing Parent", "Whether the runner child incident already had any IcM parent."),
        ("Team", "Owning team for the runner child incident."),
        ("Title", "Trimmed runner child incident title for context."),
    ],
    "succeeded": [
        ("Result", "Success type: linked relationship evidence or found-parent description evidence."),
        ("Runner ICM", "The runner child incident that succeeded proactive matching."),
        ("Proactive Parent", "The proactive parent incident matched to the runner child."),
        ("Evidence Date", "Date when the relationship or description evidence was observed."),
        ("Team", "Owning team for the runner child incident."),
        ("Title", "Trimmed runner child incident title for context."),
    ],
}


@dataclass(frozen=True)
class KpiWindow:
    previous_start: date
    previous_end_exclusive: date
    current_start: date
    current_end_exclusive: date

    @property
    def previous_label(self) -> str:
        return month_label(self.previous_start, self.previous_end_exclusive)

    @property
    def current_label(self) -> str:
        return month_label(self.current_start, self.current_end_exclusive)

    @property
    def previous_display_range(self) -> str:
        return f"{self.previous_start.isoformat()} to {(self.previous_end_exclusive - timedelta(days=1)).isoformat()}"

    @property
    def current_display_range(self) -> str:
        return f"{self.current_start.isoformat()} to {(self.current_end_exclusive - timedelta(days=1)).isoformat()}"

    @property
    def previous_start_time(self) -> datetime:
        return datetime.combine(self.previous_start, time.min)

    @property
    def current_end_time(self) -> datetime:
        return datetime.combine(self.current_end_exclusive, time.min)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Runner proactive scan KPI HTML report.")
    parser.add_argument("--month", help="Current KPI calendar month, for example 2026-04. Defaults to the last full calendar month.")
    parser.add_argument("--previous-month", help="Comparison month in YYYY-MM. Defaults to the calendar month before --month.")
    parser.add_argument("--start", help="Inclusive current-period start date. Overrides --month when paired with --end.")
    parser.add_argument("--end", help="Inclusive current-period end date. Overrides --month when paired with --start.")
    parser.add_argument("--previous-start", help="Inclusive previous-period start date for custom ranges.")
    parser.add_argument("--previous-end", help="Inclusive previous-period end date for custom ranges.")
    parser.add_argument("--out", type=Path, help="HTML output path. Defaults to report/output/proactive-scan-kpi-YYYY-MM.html.")
    parser.add_argument("--kql", type=Path, default=DEFAULT_KQL, help="Source proactive KQL path.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Directory for cached proactive CSV results.")
    parser.add_argument("--use-cache", action="store_true", help="Use the cached proactive CSV when present.")
    parser.add_argument("--cache-only", action="store_true", help="Do not query Kusto. Missing cache becomes an empty report.")
    parser.add_argument("--strict", action="store_true", help="Fail if the live Kusto query fails.")
    parser.add_argument("--auth", choices=["interactive", "device", "azcli", "msi"], default="interactive", help="Kusto authentication mode.")
    parser.add_argument("--target", type=float, default=70.0, help="Completion percentage target used for the status badge.")
    parser.add_argument("--limit-details", type=int, default=80, help="Maximum action-detail rows to show.")
    parser.add_argument("--render-kql", type=Path, help="Write the rendered KQL to this path for audit/debugging.")
    return parser.parse_args()


def add_months(month_start: date, offset: int) -> date:
    month_index = month_start.month - 1 + offset
    year = month_start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def parse_month(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM month, got {value!r}")
    year_text, month_text = value.split("-")
    month_number = int(month_text)
    if month_number < 1 or month_number > 12:
        raise argparse.ArgumentTypeError(f"Expected month 01-12, got {value!r}")
    return date(int(year_text), month_number, 1)


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM-DD date, got {value!r}") from error


def month_label(start_date: date, end_exclusive: date) -> str:
    if start_date.day == 1 and end_exclusive == add_months(start_date, 1):
        return start_date.strftime("%Y-%m")
    return f"{start_date.isoformat()}..{(end_exclusive - timedelta(days=1)).isoformat()}"


def default_current_month(today: date | None = None) -> date:
    reference_date = today or date.today()
    return add_months(date(reference_date.year, reference_date.month, 1), -1)


def build_window(args: argparse.Namespace) -> KpiWindow:
    if args.start or args.end:
        if not args.start or not args.end:
            raise ValueError("--start and --end must be supplied together")
        current_start = parse_iso_date(args.start)
        current_end_exclusive = parse_iso_date(args.end) + timedelta(days=1)
        if current_end_exclusive <= current_start:
            raise ValueError("--end must be on or after --start")
        duration = current_end_exclusive - current_start
        if args.previous_start or args.previous_end:
            if not args.previous_start or not args.previous_end:
                raise ValueError("--previous-start and --previous-end must be supplied together")
            previous_start = parse_iso_date(args.previous_start)
            previous_end_exclusive = parse_iso_date(args.previous_end) + timedelta(days=1)
        else:
            previous_end_exclusive = current_start
            previous_start = previous_end_exclusive - duration
        return KpiWindow(previous_start, previous_end_exclusive, current_start, current_end_exclusive)

    current_month = parse_month(args.month) if args.month else default_current_month()
    previous_month = parse_month(args.previous_month) if args.previous_month else add_months(current_month, -1)
    return KpiWindow(previous_month, add_months(previous_month, 1), current_month, add_months(current_month, 1))


def ensure_pandas():
    runner_report.initialize_data_modules()
    return runner_report.pd


def kusto_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def read_source_kql(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if lines and lines[0].strip().lower().startswith("http"):
        lines = lines[1:]
    return "\n".join(lines).strip() + "\n"


def render_kql(kql_path: Path, window: KpiWindow) -> str:
    source = read_source_kql(kql_path)
    query_start = window.previous_start_time - timedelta(seconds=1)
    rendered, replacements = re.subn(
        r"let\s+lookBackTm\s*=\s*datetime\([^)]*\);",
        f"let lookBackTm = datetime({kusto_datetime(query_start)});\nlet reportEndTm = datetime({kusto_datetime(window.current_end_time)});",
        source,
        count=1,
    )
    if replacements != 1:
        raise ValueError(f"Could not find the lookBackTm declaration in {kql_path}")
    return rendered.rstrip() + "\n| where LinkedDate < reportEndTm\n"


def cache_path(cache_dir: Path, window: KpiWindow) -> Path:
    file_name = f"{window.previous_label}_{window.current_label}_proactive_scan_detail.csv".replace("/", "-").replace("..", "_")
    return cache_dir / file_name


def load_or_query(args: argparse.Namespace, window: KpiWindow, query_text: str):
    pd = ensure_pandas()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    dataset_cache_path = cache_path(args.cache_dir, window)
    if (args.use_cache or args.cache_only) and dataset_cache_path.exists():
        print(f"[cache] proactive_scan: {dataset_cache_path}")
        return pd.read_csv(dataset_cache_path)
    if args.cache_only:
        print(f"[cache-miss] proactive_scan: using empty dataset")
        return pd.DataFrame(columns=EXPECTED_COLUMNS)
    print("[query] proactive_scan: https://icmcluster.kusto.windows.net / IcMDataWarehouse")
    try:
        frame = runner_report.execute_kusto_query("https://icmcluster.kusto.windows.net", "IcMDataWarehouse", query_text, args.auth)
    except Exception as error:
        if args.strict:
            raise
        print(f"[query-error] proactive_scan: {error}")
        return pd.DataFrame(columns=EXPECTED_COLUMNS)
    frame.to_csv(dataset_cache_path, index=False)
    print(f"[cache-write] proactive_scan: {dataset_cache_path}")
    return frame


def text_value(value: Any, default: str = "") -> str:
    pd = runner_report.pd
    if value is None:
        return default
    if pd is not None and pd.isna(value):
        return default
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.lower() in {"", "nan", "nat", "none"}:
        return default
    return text


def truncate_text(value: Any, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", text_value(value)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def clean_result(value: Any) -> str:
    result = text_value(value, "NotLinked")
    aliases = {
        "notlinked": "NotLinked",
        "completed": "Completed",
        "linked": "Completed",
        "incompleted": "Incompleted",
        "incomplete": "Incompleted",
        "foundparent": "Incompleted",
        "proactivefailed": "ProactiveFailed",
        "databasedown": "DatabaseDown",
    }
    return aliases.get(result.replace(" ", "").lower(), result)


def normalize_frame(frame):
    pd = ensure_pandas()
    if frame is None or frame.empty:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)
    normalized = frame.copy()
    for column in EXPECTED_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = None
    for date_column in ["LinkedDate", "EvidenceDate"]:
        normalized[date_column] = pd.to_datetime(normalized[date_column], errors="coerce", utc=True).dt.tz_convert(None)
    normalized["LinkResult"] = normalized["LinkResult"].map(clean_result)
    for column in ["HasExistingParent", "HasProactiveParent", "IsProactivelyLinked"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0).astype(int)
    return normalized


def filter_period(frame, start_date: date, end_exclusive: date):
    start_time = datetime.combine(start_date, time.min)
    end_time = datetime.combine(end_exclusive, time.min)
    if frame.empty or "LinkedDate" not in frame.columns:
        return frame.iloc[0:0].copy()
    mask = (frame["LinkedDate"] >= start_time) & (frame["LinkedDate"] < end_time)
    return frame.loc[mask].copy()


def result_counts(frame) -> dict[str, int]:
    counts = {result: 0 for result in RESULT_ORDER}
    if frame.empty or "LinkResult" not in frame.columns:
        return counts
    raw_counts = frame["LinkResult"].fillna("NotLinked").map(clean_result).value_counts()
    for result, count in raw_counts.items():
        counts[text_value(result, "Unknown")] = int(count)
    return counts


def successful_count(counts: dict[str, int]) -> int:
    return sum(counts.get(result, 0) for result in SUCCESS_RESULTS)


def failed_count(counts: dict[str, int]) -> int:
    return sum(counts.get(result, 0) for result in FAILURE_RESULTS)


def build_metrics(frame) -> dict[str, Any]:
    counts = result_counts(frame)
    total = int(len(frame))
    completed = counts.get("Completed", 0)
    successful = successful_count(counts)
    not_linked = counts.get("NotLinked", 0)
    attempted = max(0, total - not_linked)
    failed = failed_count(counts)
    success_rate = None if total == 0 else successful / total * 100
    return {
        "total": total,
        "counts": counts,
        "completed": completed,
        "successful": successful,
        "attempted": attempted,
        "failed": failed,
        "completion_rate": success_rate,
        "success_rate": success_rate,
        "attempt_rate": None if total == 0 else attempted / total * 100,
        "existing_parent": int(frame["HasExistingParent"].sum()) if not frame.empty and "HasExistingParent" in frame.columns else 0,
        "proactive_parent": int(frame["HasProactiveParent"].sum()) if not frame.empty and "HasProactiveParent" in frame.columns else 0,
    }


def format_rate(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%"


def format_delta(current: int, previous: int) -> str:
    return f"{current - previous:+d}"


def format_delta_pp(current_rate: float | None, previous_rate: float | None) -> str:
    if current_rate is None or previous_rate is None:
        return "-"
    return f"{current_rate - previous_rate:+.1f}pp"


def status_badge(label: str, css_class: str) -> str:
    return f'<span class="badge {css_class}">{html.escape(label)}</span>'


def rate_status(rate: float | None, target: float) -> str:
    if rate is None:
        return status_badge("no data", "gray")
    if rate >= target:
        return status_badge("on target", "green")
    if rate >= max(0.0, target - 15.0):
        return status_badge("trending", "yellow")
    return status_badge("in focus", "red")


def lower_is_better_status(current: int, previous: int) -> str:
    if current == 0:
        return status_badge("clear", "green")
    if current <= previous:
        return status_badge("improving", "yellow")
    return status_badge("in focus", "red")


def higher_is_better_status(current: int, previous: int) -> str:
    if current >= previous:
        return status_badge("improving", "green")
    return status_badge("watch", "yellow")


def table(headers: list[str], rows: list[list[str]], row_classes: list[str] | None = None) -> str:
    header_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body_rows = []
    for index, row in enumerate(rows):
        css_class = f' class="{row_classes[index]}"' if row_classes and row_classes[index] else ""
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows.append(f"<tr{css_class}>{cells}</tr>")
    if not body_rows:
        body_rows.append(f"<tr><td colspan=\"{len(headers)}\">No data for this period</td></tr>")
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def icm_anchor(incident_id: Any, link: Any = None) -> str:
    incident_text = text_value(incident_id)
    if not incident_text:
        return "&mdash;"
    link_text = text_value(link) or f"https://portal.microsofticm.com/imp/v5/incidents/details/{incident_text}/summary"
    return f'<a href="{html.escape(link_text, quote=True)}" target="_blank">{html.escape(incident_text)}</a>'


def yes_no(value: Any) -> str:
    return "Yes" if text_value(value, "0") in {"1", "True", "true", "yes", "Yes"} else "No"


def row_date_text(row, *columns: str) -> str:
    pd = runner_report.pd
    for column in columns:
        value = row.get(column)
        if pd is not None and pd.isna(value):
            continue
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        text = text_value(value)
        if text:
            return text[:10]
    return "-"


def result_css_class(result: str) -> str:
    return "result-" + clean_result(result).lower()


def pct(part: int, total: int) -> str:
    if total == 0:
        return "-"
    return f"{part / total * 100:.1f}%"


def column_definitions(key: str) -> str:
    definitions = COLUMN_DEFINITIONS.get(key, [])
    if not definitions:
        return ""
    rows = "".join(
        f"<dt>{html.escape(column)}</dt><dd>{html.escape(description)}</dd>"
        for column, description in definitions
    )
    return f'<div class="column-definitions"><div class="definition-title">Column definitions</div><dl>{rows}</dl></div>'


def build_overview_table(previous_metrics: dict[str, Any], current_metrics: dict[str, Any], target: float) -> str:
    previous_counts = previous_metrics["counts"]
    current_counts = current_metrics["counts"]
    previous_success = previous_metrics["successful"]
    current_success = current_metrics["successful"]
    rows = [
        [
            "Proactive success %",
            f"&gt; {target:.0f}%",
            format_rate(previous_metrics["success_rate"]),
            f'<span class="metric-current">{format_rate(current_metrics["success_rate"])}</span>',
            format_delta_pp(current_metrics["success_rate"], previous_metrics["success_rate"]),
            rate_status(current_metrics["success_rate"], target),
        ],
        [
            "Succeeded (linked/found)",
            "higher",
            str(previous_success),
            f'<span class="metric-current">{current_success}</span>',
            format_delta(current_success, previous_success),
            higher_is_better_status(current_success, previous_success),
        ],
        [
            "Failure - others",
            "0",
            str(previous_counts.get("ProactiveFailed", 0)),
            f'<span class="metric-current">{current_counts.get("ProactiveFailed", 0)}</span>',
            format_delta(current_counts.get("ProactiveFailed", 0), previous_counts.get("ProactiveFailed", 0)),
            lower_is_better_status(current_counts.get("ProactiveFailed", 0), previous_counts.get("ProactiveFailed", 0)),
        ],
        [
            "Failure - database down",
            "0",
            str(previous_counts.get("DatabaseDown", 0)),
            f'<span class="metric-current">{current_counts.get("DatabaseDown", 0)}</span>',
            format_delta(current_counts.get("DatabaseDown", 0), previous_counts.get("DatabaseDown", 0)),
            lower_is_better_status(current_counts.get("DatabaseDown", 0), previous_counts.get("DatabaseDown", 0)),
        ],
        [
            "Not linked",
            "lower",
            str(previous_counts.get("NotLinked", 0)),
            f'<span class="metric-current">{current_counts.get("NotLinked", 0)}</span>',
            format_delta(current_counts.get("NotLinked", 0), previous_counts.get("NotLinked", 0)),
            lower_is_better_status(current_counts.get("NotLinked", 0), previous_counts.get("NotLinked", 0)),
        ],
    ]
    return table(["KPI", "Target", "Previous", "Current", "Delta", "Status"], rows)


def build_summary_table(window: KpiWindow, previous_metrics: dict[str, Any], current_metrics: dict[str, Any]) -> str:
    rows = []
    for label, metrics, current in [
        (window.previous_label, previous_metrics, False),
        (window.current_label, current_metrics, True),
    ]:
        counts = metrics["counts"]
        rate = format_rate(metrics["success_rate"])
        rate_cell = f'<span class="metric-current">{rate}</span>' if current else rate
        rows.append([
            html.escape(label),
            str(metrics["total"]),
            str(metrics["successful"]),
            str(counts.get("Completed", 0)),
            str(counts.get("Incompleted", 0)),
            str(counts.get("ProactiveFailed", 0)),
            str(counts.get("DatabaseDown", 0)),
            str(counts.get("NotLinked", 0)),
            rate_cell,
            format_rate(metrics["attempt_rate"]),
        ])
    return table(
        ["Month", "Total CP", "Succeeded", "Linked", "Found parent", "Failure - others", "Failure - database down", "Not linked", "Success %", "Scan attempt %"],
        rows,
    )


def build_parent_coverage_table(window: KpiWindow, previous_metrics: dict[str, Any], current_metrics: dict[str, Any]) -> str:
    rows = []
    for label, metrics, current in [(window.previous_label, previous_metrics, False), (window.current_label, current_metrics, True)]:
        total = metrics["total"]
        existing = metrics["existing_parent"]
        proactive = metrics["proactive_parent"]
        rows.append([
            html.escape(label),
            str(total),
            str(existing),
            pct(existing, total),
            f'<span class="metric-current">{proactive}</span>' if current else str(proactive),
            pct(proactive, total),
        ])
    return table(["Month", "Total CP", "Has existing parent", "Existing parent %", "Has proactive parent", "Proactive parent %"], rows)


def stacked_result_svg(window: KpiWindow, previous_metrics: dict[str, Any], current_metrics: dict[str, Any]) -> str:
    width = 900
    height = 190
    left = 92
    bar_width = 520
    rows = [(window.previous_label, previous_metrics, 52), (window.current_label, current_metrics, 112)]
    parts = [f'<svg class="report-chart" width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
    parts.append('<text x="80" y="22" font-size="13" font-weight="600" fill="#0E2841">Proactive scan result distribution</text>')
    for label, metrics, y_pos in rows:
        total = metrics["total"]
        parts.append(f'<text x="78" y="{y_pos + 17}" font-size="13" text-anchor="end" fill="#1a1a1a" font-weight="600">{html.escape(label)}</text>')
        if total == 0:
            parts.append(f'<rect x="{left}" y="{y_pos}" width="{bar_width}" height="26" fill="#f0f3f7" />')
            parts.append(f'<text x="{left + 12}" y="{y_pos + 17}" font-size="12" fill="#6e7781">No data</text>')
            continue
        cursor = left
        for result in RESULT_ORDER:
            count = metrics["counts"].get(result, 0)
            if count == 0:
                continue
            segment_width = max(1.0, count / total * bar_width)
            color = RESULT_COLORS.get(result, RESULT_COLORS["Unknown"])
            parts.append(f'<rect x="{cursor:.1f}" y="{y_pos}" width="{segment_width:.1f}" height="26" fill="{color}" />')
            if segment_width >= 42:
                parts.append(f'<text x="{cursor + segment_width / 2:.1f}" y="{y_pos + 17}" font-size="11" font-weight="600" text-anchor="middle" fill="#fff">{count}</text>')
            cursor += segment_width
        parts.append(f'<text x="{left + bar_width + 16}" y="{y_pos + 17}" font-size="12" fill="#444">Succeeded {metrics["successful"]}/{total} ({format_rate(metrics["success_rate"])})</text>')
    legend_x = 92
    for index, result in enumerate(RESULT_ORDER):
        x_pos = legend_x + index * 150
        parts.append(f'<rect x="{x_pos}" y="158" width="14" height="14" fill="{RESULT_COLORS[result]}" />')
        parts.append(f'<text x="{x_pos + 20}" y="169" font-size="12" fill="#444">{html.escape(RESULT_LABELS[result])}</text>')
    parts.append("</svg>")
    return '<div class="chart-wrap">' + "".join(parts) + "</div>"


def floor_to_week(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_result_svg(frame, window: KpiWindow) -> str:
    width = 900
    height = 330
    left = 56
    top = 34
    chart_width = 820
    chart_height = 220
    bottom = top + chart_height
    week_start = floor_to_week(window.previous_start)
    week_starts: list[date] = []
    while week_start < window.current_end_exclusive:
        week_starts.append(week_start)
        week_start += timedelta(days=7)
    weekly_counts = []
    for start_day in week_starts:
        period_frame = filter_period(frame, start_day, start_day + timedelta(days=7))
        counts = result_counts(period_frame)
        weekly_counts.append((start_day, counts, len(period_frame)))
    max_total = max([item[2] for item in weekly_counts] + [5])
    grid_max = max(5, int(math.ceil(max_total / 5.0) * 5))
    slot = chart_width / max(1, len(weekly_counts))
    bar_width = min(54, max(8, slot * 0.58))
    parts = [f'<svg class="report-chart" width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
    for step in range(0, grid_max + 1, max(1, grid_max // 4)):
        y_pos = bottom - step / grid_max * chart_height
        parts.append(f'<line x1="{left}" y1="{y_pos:.1f}" x2="{left + chart_width}" y2="{y_pos:.1f}" stroke="#eee" />')
        parts.append(f'<text x="{left - 8}" y="{y_pos + 4:.1f}" font-size="10" text-anchor="end" fill="#666">{step}</text>')
    boundary_x = left + ((datetime.combine(window.current_start, time.min) - datetime.combine(week_starts[0], time.min)).days / 7 + 0.5) * slot
    parts.append(f'<line x1="{boundary_x:.1f}" y1="{top}" x2="{boundary_x:.1f}" y2="{bottom}" stroke="#156082" stroke-width="1.5" stroke-dasharray="5 4" />')
    parts.append(f'<text x="{boundary_x + 6:.1f}" y="{top + 12}" font-size="10" fill="#156082" font-weight="600">{html.escape(window.current_label)}</text>')
    for index, (start_day, counts, total) in enumerate(weekly_counts):
        x_center = left + index * slot + slot / 2
        x_pos = x_center - bar_width / 2
        cursor_y = bottom
        if total == 0:
            parts.append(f'<rect x="{x_pos:.1f}" y="{bottom - 1}" width="{bar_width:.1f}" height="1" fill="#d0d7de" />')
        else:
            for result in reversed(RESULT_ORDER):
                count = counts.get(result, 0)
                if count == 0:
                    continue
                segment_height = max(1.0, count / grid_max * chart_height)
                cursor_y -= segment_height
                parts.append(f'<rect x="{x_pos:.1f}" y="{cursor_y:.1f}" width="{bar_width:.1f}" height="{segment_height:.1f}" fill="{RESULT_COLORS[result]}" opacity="0.9" />')
            parts.append(f'<text x="{x_center:.1f}" y="{cursor_y - 5:.1f}" font-size="10" text-anchor="middle" fill="#0E2841" font-weight="600">{total}</text>')
        label = start_day.strftime("%m-%d")
        parts.append(f'<text x="{x_center:.1f}" y="{bottom + 20}" font-size="10" text-anchor="middle" fill="#444" transform="rotate(-30 {x_center:.1f} {bottom + 20})">{label}</text>')
    parts.append(f'<text x="14" y="{top + chart_height / 2:.1f}" font-size="11" text-anchor="middle" fill="#444" transform="rotate(-90 14 {top + chart_height / 2:.1f})">CP Sev2/2.5 count</text>')
    parts.append("</svg>")
    return '<div class="chart-wrap">' + "".join(parts) + "</div>"


def team_breakdown_table(current_frame) -> str:
    if current_frame.empty:
        return table(["Owning Team", "Total", "Succeeded", "Failed", "Not linked", "Success %", "Sample IcM"], [])
    rows = []
    work = current_frame.copy()
    work["OwningTeamName"] = work["OwningTeamName"].map(lambda value: text_value(value, "Unknown"))
    grouped = work.groupby("OwningTeamName", dropna=False)
    for team, group in grouped:
        counts = result_counts(group)
        total = len(group)
        successful = successful_count(counts)
        failed = failed_count(counts)
        samples = ", ".join(icm_anchor(row.get("RunnerIncidentId"), row.get("ChildIncidentLink")) for _, row in group.head(3).iterrows())
        rows.append({
            "team": text_value(team, "Unknown"),
            "total": total,
            "successful": successful,
            "failed": failed,
            "not_linked": counts.get("NotLinked", 0),
            "rate": None if total == 0 else successful / total * 100,
            "samples": samples,
        })
    rows.sort(key=lambda item: (item["total"], item["failed"], item["not_linked"]), reverse=True)
    html_rows = [
        [
            html.escape(row["team"]),
            str(row["total"]),
            str(row["successful"]),
            str(row["failed"]),
            str(row["not_linked"]),
            format_rate(row["rate"]),
            row["samples"] or "&mdash;",
        ]
        for row in rows[:15]
    ]
    return table(["Owning Team", "Total", "Succeeded", "Failed", "Not linked", "Success %", "Sample IcM"], html_rows)


def parent_group_table(current_frame) -> str:
    if current_frame.empty:
        return table(["Proactive Parent", "Result Mix", "Children", "Status", "Sample Runner ICM", "Title"], [])
    linked = current_frame[current_frame["ProactiveParentIncidentId"].map(lambda value: bool(text_value(value)))].copy()
    if linked.empty:
        return table(["Proactive Parent", "Result Mix", "Children", "Status", "Sample Runner ICM", "Title"], [])
    rows = []
    grouped = linked.groupby(["ProactiveParentIncidentId", "ProactiveTitle"], dropna=False)
    for (parent_id, title), group in grouped:
        counts = result_counts(group)
        total = len(group)
        result_mix = ", ".join(f"{RESULT_LABELS.get(result, result)} {count}" for result, count in counts.items() if count)
        sample = ", ".join(icm_anchor(row.get("RunnerIncidentId"), row.get("ChildIncidentLink")) for _, row in group.head(4).iterrows())
        parent_link = group.iloc[0].get("ProactiveIncidentLink")
        rows.append({
            "parent": icm_anchor(parent_id, parent_link),
            "mix": html.escape(result_mix or "Unknown"),
            "total": total,
            "status": html.escape(text_value(group.iloc[0].get("Status"), "-")),
            "sample": sample,
            "title": html.escape(truncate_text(title, 150)),
            "sort": total,
        })
    rows.sort(key=lambda item: item["sort"], reverse=True)
    html_rows = [[row["parent"], row["mix"], str(row["total"]), row["status"], row["sample"], row["title"]] for row in rows[:20]]
    return table(["Proactive Parent", "Result Mix", "Children", "Status", "Sample Runner ICM", "Title"], html_rows)


def action_detail_table(current_frame, limit: int) -> str:
    if current_frame.empty:
        return table(["Result", "Runner ICM", "Proactive Parent", "Sev", "Date", "Existing Parent", "Team", "Title"], [])
    priority = {"ProactiveFailed": 0, "DatabaseDown": 1, "NotLinked": 2}
    detail = current_frame[~current_frame["LinkResult"].map(clean_result).isin(SUCCESS_RESULTS)].copy()
    if detail.empty:
        return table(["Result", "Runner ICM", "Proactive Parent", "Sev", "Date", "Existing Parent", "Team", "Title"], [])
    detail["SortPriority"] = detail["LinkResult"].map(lambda result: priority.get(clean_result(result), 9))
    detail = detail.sort_values(["SortPriority", "LinkedDate"], ascending=[True, False])
    rows = []
    row_classes = []
    for _, row in detail.head(limit).iterrows():
        result = clean_result(row.get("LinkResult"))
        date_text = row_date_text(row, "EvidenceDate", "LinkedDate")
        rows.append([
            html.escape(RESULT_LABELS.get(result, result)),
            icm_anchor(row.get("RunnerIncidentId"), row.get("ChildIncidentLink")),
            icm_anchor(row.get("ProactiveParentIncidentId"), row.get("ProactiveIncidentLink")),
            html.escape(text_value(row.get("Severity"), "-")),
            html.escape(date_text),
            html.escape(yes_no(row.get("HasExistingParent"))),
            html.escape(text_value(row.get("OwningTeamName"), "Unknown")),
            html.escape(truncate_text(row.get("RunnerTitle"), 180)),
        ])
        row_classes.append(result_css_class(result))
    return table(["Result", "Runner ICM", "Proactive Parent", "Sev", "Date", "Existing Parent", "Team", "Title"], rows, row_classes)


def succeeded_sample_table(current_frame) -> str:
    if current_frame.empty:
        return table(["Result", "Runner ICM", "Proactive Parent", "Evidence Date", "Team", "Title"], [])
    succeeded = current_frame[current_frame["LinkResult"].map(clean_result).isin(SUCCESS_RESULTS)].copy()
    if succeeded.empty:
        return table(["Result", "Runner ICM", "Proactive Parent", "Evidence Date", "Team", "Title"], [])
    succeeded = succeeded.sort_values("LinkedDate", ascending=False)
    rows = []
    row_classes = []
    for _, row in succeeded.head(25).iterrows():
        result = clean_result(row.get("LinkResult"))
        date_text = row_date_text(row, "EvidenceDate", "LinkedDate")
        rows.append([
            html.escape(RESULT_LABELS.get(result, result)),
            icm_anchor(row.get("RunnerIncidentId"), row.get("ChildIncidentLink")),
            icm_anchor(row.get("ProactiveParentIncidentId"), row.get("ProactiveIncidentLink")),
            html.escape(date_text),
            html.escape(text_value(row.get("OwningTeamName"), "Unknown")),
            html.escape(truncate_text(row.get("RunnerTitle"), 170)),
        ])
        row_classes.append(result_css_class(result))
    return table(["Result", "Runner ICM", "Proactive Parent", "Evidence Date", "Team", "Title"], rows, row_classes)


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def build_html(frame, window: KpiWindow, args: argparse.Namespace, cache_file: Path) -> str:
    current_frame = filter_period(frame, window.current_start, window.current_end_exclusive)
    previous_frame = filter_period(frame, window.previous_start, window.previous_end_exclusive)
    current_metrics = build_metrics(current_frame)
    previous_metrics = build_metrics(previous_frame)
    generated_at = datetime.now().replace(microsecond=0).isoformat()
    title = f"Runner Proactive Scan KPI Report - {window.previous_label} vs {window.current_label}"
    kql_path = relative_path(args.kql)
    cache_display = relative_path(cache_file)
    rendered_kql = relative_path(args.render_kql) if args.render_kql else "not written"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
{STYLE}
</style>
</head>
<body>
<div class="layout">
  <nav class="sidebar">
    <h1>Proactive Scan KPI</h1>
    <div class="meta">{html.escape(window.previous_label)} vs {html.escape(window.current_label)}<br>{html.escape(generated_at)}</div>
    <a href="#overview">Overview</a>
    <a href="#summary">Summary</a>
    <a href="#trend">Weekly Trend</a>
    <a href="#teams">Teams</a>
    <a href="#parents">Parents</a>
    <a href="#details">Action Details</a>
    <a href="#succeeded">Succeeded Samples</a>
    <a href="#notes">Notes</a>
  </nav>
  <main class="content">
    <h2 id="overview">Status Overview</h2>
    <p>Control Path Runner Sev2/2.5 incidents from {html.escape(window.previous_display_range)} compared with {html.escape(window.current_display_range)}. Success % counts proactive duplicate links plus proactive parents found through the description fallback, divided by all CP runner children in the period.</p>
    {column_definitions("overview")}
    {build_overview_table(previous_metrics, current_metrics, args.target)}

    <h2 id="summary">Proactive Scan Summary</h2>
    {column_definitions("summary")}
    {build_summary_table(window, previous_metrics, current_metrics)}
    {stacked_result_svg(window, previous_metrics, current_metrics)}

    <h3>Parent Coverage</h3>
    {column_definitions("parent_coverage")}
    {build_parent_coverage_table(window, previous_metrics, current_metrics)}

    <h2 id="trend">Weekly Trend</h2>
    <p>Weekly stacked counts use <code>LinkedDate</code>. For unlinked runner children, <code>LinkedDate</code> is the child incident create date from the KQL.</p>
    {weekly_result_svg(frame, window)}

    <h2 id="teams">Current Month by Owning Team</h2>
    {column_definitions("teams")}
    {team_breakdown_table(current_frame)}

    <h2 id="parents">Current Month by Proactive Parent</h2>
    <p>Grouped where a proactive parent incident was found through duplicate relationship evidence or the description-based fallback.</p>
    {column_definitions("parents")}
    {parent_group_table(current_frame)}

    <h2 id="details">Current Month Action Details</h2>
    <p>Rows needing action: failure - others, failure - database down, and not-linked children, ordered by result and then newest linked date.</p>
    {column_definitions("details")}
    {action_detail_table(current_frame, args.limit_details)}

    <h2 id="succeeded">Succeeded Samples</h2>
    {column_definitions("succeeded")}
    {succeeded_sample_table(current_frame)}

    <h2 id="notes">Notes</h2>
    <div class="notes">
      <ul>
        <li>Source KQL: <code>{html.escape(kql_path)}</code></li>
        <li>CSV cache: <code>{html.escape(cache_display)}</code></li>
        <li>Rendered KQL: <code>{html.escape(rendered_kql)}</code></li>
        <li>The report removes the data-explorer URL line from the source KQL, replaces <code>lookBackTm</code> with the previous-period start, and filters output to before the current-period end.</li>
        <li><code>Succeeded</code> combines duplicate relationship evidence (<code>Linked</code>) and description-based parent evidence (<code>Found parent</code>). <code>Failure - others</code> and <code>Failure - database down</code> come from Eureka proactive triage failure text.</li>
      </ul>
    </div>
    <p class="kusto-footnote">Generated from cached or live Kusto query results. Re-run with <code>--use-cache</code> for deterministic offline rendering.</p>
  </main>
</div>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    window = build_window(args)
    if args.out is None:
        args.out = DEFAULT_OUTPUT_DIR / f"proactive-scan-kpi-{window.current_label}.html".replace("/", "-").replace("..", "_")
    query_text = render_kql(args.kql, window)
    if args.render_kql:
        args.render_kql.parent.mkdir(parents=True, exist_ok=True)
        args.render_kql.write_text(query_text, encoding="utf-8")
        print(f"[render-kql] {args.render_kql}")
    raw_frame = load_or_query(args, window, query_text)
    frame = normalize_frame(raw_frame)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report_html = build_html(frame, window, args, cache_path(args.cache_dir, window))
    args.out.write_text(report_html, encoding="utf-8")
    print(f"[html] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())