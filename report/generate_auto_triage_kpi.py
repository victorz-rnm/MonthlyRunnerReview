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
DEFAULT_KQL = WORKSPACE_ROOT / "KPI" / "Analyze Runner Sev2" / "auto_triage_kpi_complete - advance.kql"
DEFAULT_CACHE_DIR = SCRIPT_DIR / "output" / "cache"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"

RESULT_SET_NAMES = ["incident_level", "team_level", "overall"]
RESULT_SET_LABELS = {
    "incident_level": "IncidentLevelKpi",
    "team_level": "TeamLevelKpi",
    "overall": "OverallKpi",
}

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
td:last-child { max-width: 720px; line-height: 1.4; word-break: break-word; }
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
.chart-wrap { margin: 12px 0 22px; overflow-x: auto; }
svg.report-chart { background:#fff; border:1px solid #e1e4e8; border-radius:6px; max-width: 100%; height: auto; }
tr.row-good td { background: #f0fdf4 !important; }
tr.row-watch td { background: #fffbe6 !important; }
tr.row-focus td { background: #fff1f0 !important; }
tr.row-muted td { background: #f5f5f5 !important; color: #6e7781; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { position: static; height: auto; }
  .content { padding: 24px 16px; }
  .column-definitions dl { grid-template-columns: 1fr; }
}
""".strip()


COLUMN_DEFINITIONS: dict[str, list[tuple[str, str]]] = {
    "overview": [
        ("KPI", "The auto-triage quality metric being evaluated for the previous and current periods."),
        ("Report Target", "The report-side target or preferred threshold for the KPI."),
        ("Previous", "Value from the previous comparison period."),
        ("Current", "Value from the current reporting period; highlighted for scan reading."),
        ("Delta", "Current value minus previous value. Rate deltas are percentage points."),
        ("Status", "Badge based on the current value compared with the report target."),
    ],
    "definitions": [
        ("Term", "Name of the KPI term, abbreviation, or report convention."),
        ("Meaning", "Plain-language definition used by the report and presenter."),
    ],
    "monthly_summary": [
        ("Month", "The reporting period represented by the row."),
        ("Eligible", "Eligible Sev2/2.5 incidents originally created in target teams during the period."),
        ("Auto transfers", "Eligible incidents that received an auto-triage transfer action."),
        ("Auto links", "Eligible incidents that received an auto-triage relationship/link action."),
        ("Any auto", "Eligible incidents with either an auto transfer or an auto link."),
        ("Coverage", "Any auto divided by Eligible."),
        ("Transfer correct", "Auto transfers not later corrected by a manual transfer."),
        ("Link correct", "Auto links not later corrected by a manual relationship update."),
        ("Rework", "Rows where the matching auto action was later manually corrected."),
        ("Rework %", "Rework divided by Any auto."),
        ("First auto p50", "Median time from incident creation to the first auto-triage action."),
        ("First auto p95", "95th percentile time from incident creation to the first auto-triage action."),
    ],
    "row_color_legend": [
        ("Row color", "Visual warning category applied to team rollup rows."),
        ("Meaning", "Condition that causes the row color."),
    ],
    "team_rollup": [
        ("Original Team", "Owning team on the eligible incident at creation time."),
        ("Eligible", "Eligible incidents originally created in that team."),
        ("Any Auto", "Incidents from the team with either an auto transfer or auto link."),
        ("Coverage", "Any Auto divided by Eligible for the team."),
        ("Transfer Correct", "Correct auto transfer rate for the team."),
        ("Link Correct", "Correct auto link rate for the team."),
        ("Rework", "Team rework rate: matching-action corrections divided by Any Auto."),
        ("First Auto P50", "Median first-auto-action latency for the team."),
        ("First Auto P95", "95th percentile first-auto-action latency for the team."),
    ],
    "overall_rollup": [
        ("Metric", "Overall KPI count, rate, or latency across the full rendered report window."),
        ("Value", "Computed value for the metric after report-side rework reconciliation."),
    ],
    "rework_details": [
        ("Incident", "IcM incident where the matching auto action was later corrected."),
        ("Created", "Original incident creation timestamp."),
        ("Original Team", "Owning team at incident creation time."),
        ("Current Team", "Current owning team from the incident-level result set."),
        ("Manual Correction", "Type of later manual correction: transfer, relationship, or both."),
        ("First Auto", "Timestamp of the first auto-triage action on the incident."),
        ("Title", "Trimmed incident title for context."),
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
    def query_start_time(self) -> datetime:
        return datetime.combine(self.previous_start, time.min)

    @property
    def query_end_time(self) -> datetime:
        return datetime.combine(self.current_end_exclusive, time.min)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Runner auto-triage KPI HTML report.")
    parser.add_argument("--month", help="Current KPI calendar month, for example 2026-04. Defaults to the last full calendar month.")
    parser.add_argument("--previous-month", help="Comparison month in YYYY-MM. Defaults to the calendar month before --month.")
    parser.add_argument("--start", help="Inclusive current-period start date. Overrides --month when paired with --end.")
    parser.add_argument("--end", help="Inclusive current-period end date. Overrides --month when paired with --start.")
    parser.add_argument("--previous-start", help="Inclusive previous-period start date for custom ranges.")
    parser.add_argument("--previous-end", help="Inclusive previous-period end date for custom ranges.")
    parser.add_argument("--out", type=Path, help="HTML output path. Defaults to report/output/auto-triage-kpi-YYYY-MM.html.")
    parser.add_argument("--kql", type=Path, default=DEFAULT_KQL, help="Source auto-triage KPI KQL path.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Directory for cached CSV query results.")
    parser.add_argument("--use-cache", action="store_true", help="Use cached CSVs when all three result-set caches are present.")
    parser.add_argument("--cache-only", action="store_true", help="Do not query Kusto. Missing caches become empty datasets.")
    parser.add_argument("--strict", action="store_true", help="Fail if the live Kusto query fails.")
    parser.add_argument("--auth", choices=["interactive", "device", "azcli", "msi"], default="interactive", help="Kusto authentication mode.")
    parser.add_argument("--coverage-target", type=float, default=15.0, help="Auto-any coverage target percentage.")
    parser.add_argument("--correctness-target", type=float, default=90.0, help="Transfer/link correctness target percentage.")
    parser.add_argument("--rework-target", type=float, default=10.0, help="Maximum acceptable rework rate percentage.")
    parser.add_argument("--latency-target-minutes", type=float, default=30.0, help="Maximum desired first-auto-action p50 latency in minutes.")
    parser.add_argument("--limit-incidents", type=int, default=0, help="Deprecated. Incident-level rows are cached but not rendered in the HTML.")
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
    return path.read_text(encoding="utf-8-sig").strip() + "\n"


def render_kql(kql_path: Path, window: KpiWindow) -> str:
    source = read_source_kql(kql_path)
    rendered, replacements = re.subn(
        r"let\s+lookBackRange\s*=\s*[^;]+;",
        "\n".join([
            f"let lookBackRange = datetime({kusto_datetime(window.query_start_time)});",
            f"let reportEndTime = datetime({kusto_datetime(window.query_end_time)});",
        ]),
        source,
        count=1,
    )
    if replacements != 1:
        raise ValueError(f"Could not find the lookBackRange declaration in {kql_path}")
    rendered = re.sub(r"\|\s*where\s+CreateDate\s*>\s*lookBackRange", "| where CreateDate >= lookBackRange and CreateDate < reportEndTime", rendered)
    rendered = re.sub(r"\|\s*where\s+ChangeDate\s*>\s*lookBackRange", "| where ChangeDate >= lookBackRange and ChangeDate < reportEndTime", rendered)
    eligible_scan = """let EligibleIncidents = materialize(
    Incidents
    | where CreateDate >= lookBackRange and CreateDate < reportEndTime
    | summarize arg_min(CreateDate, IncidentId, OwningTeamId, OwningTeamName, OwningTenantName, Severity, IncidentType, Title, CreateDate) by IncidentId
    | where OwningTeamId in (targetTeamIds)
    | where Severity in (targetSeverities)"""
    optimized_eligible_scan = """let CandidateIncidentIds = materialize(
    Incidents
    | where CreateDate >= lookBackRange and CreateDate < reportEndTime
    | where OwningTeamId in (targetTeamIds)
    | where Severity in (targetSeverities)
    | distinct IncidentId
);
let EligibleIncidents = materialize(
    Incidents
    | where CreateDate >= lookBackRange and CreateDate < reportEndTime
    | where IncidentId in (CandidateIncidentIds)
    | summarize arg_min(CreateDate, IncidentId, OwningTeamId, OwningTeamName, OwningTenantName, Severity, IncidentType, Title, CreateDate) by IncidentId
    | where OwningTeamId in (targetTeamIds)
    | where Severity in (targetSeverities)"""
    rendered = rendered.replace(eligible_scan, optimized_eligible_scan, 1)
    rendered = rendered.replace("datetime_diff('second', FirstAutoTransferAt, OriginalCreateDate), real(null)", "datetime_diff('second', FirstAutoTransferAt, OriginalCreateDate), long(null)")
    rendered = rendered.replace("datetime_diff('second', FirstAutoLinkAt, OriginalCreateDate), real(null)", "datetime_diff('second', FirstAutoLinkAt, OriginalCreateDate), long(null)")
    rendered = rendered.replace("datetime_diff('second', FirstAutoActionAt, OriginalCreateDate), real(null)", "datetime_diff('second', FirstAutoActionAt, OriginalCreateDate), long(null)")
    return rendered.rstrip() + "\n"


def cache_paths(cache_dir: Path, window: KpiWindow) -> dict[str, Path]:
    prefix = f"{window.previous_label}_{window.current_label}_auto_triage".replace("/", "-").replace("..", "_")
    return {name: cache_dir / f"{prefix}_{name}.csv" for name in RESULT_SET_NAMES}


def execute_multi_result_query(cluster_uri: str, database: str, query_text: str, auth_mode: str) -> list[Any]:
    pd = ensure_pandas()
    kusto_data = runner_report.require_module("azure.kusto.data", "azure-kusto-data")
    helper_module = runner_report.require_module("azure.kusto.data.helpers", "azure-kusto-data")
    connection_builder = kusto_data.KustoConnectionStringBuilder
    if auth_mode == "azcli":
        connection = connection_builder.with_az_cli_authentication(cluster_uri)
    elif auth_mode == "device":
        connection = connection_builder.with_aad_device_authentication(cluster_uri)
    elif auth_mode == "msi":
        connection = connection_builder.with_aad_managed_service_identity_authentication(cluster_uri)
    else:
        connection = connection_builder.with_interactive_login(cluster_uri)
    client = kusto_data.KustoClient(connection)
    response = client.execute(database, query_text)
    if not response.primary_results:
        return [pd.DataFrame() for _ in RESULT_SET_NAMES]
    return [helper_module.dataframe_from_result_table(result_table) for result_table in response.primary_results]


def load_or_query(args: argparse.Namespace, window: KpiWindow, query_text: str) -> dict[str, Any]:
    pd = ensure_pandas()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    paths = cache_paths(args.cache_dir, window)
    if (args.use_cache or args.cache_only) and all(path.exists() for path in paths.values()):
        for name, path in paths.items():
            print(f"[cache] {RESULT_SET_LABELS[name]}: {path}")
        return {name: pd.read_csv(path) for name, path in paths.items()}
    if args.cache_only:
        for name, path in paths.items():
            print(f"[cache-miss] {RESULT_SET_LABELS[name]}: {path}")
        return {name: pd.DataFrame() for name in RESULT_SET_NAMES}

    print("[query] auto_triage_kpi: https://icmcluster.kusto.windows.net / IcMDataWarehouse")
    try:
        frames = execute_multi_result_query("https://icmcluster.kusto.windows.net", "IcMDataWarehouse", query_text, args.auth)
    except Exception:
        if args.strict:
            raise
        return {name: pd.DataFrame() for name in RESULT_SET_NAMES}
    if len(frames) < 3:
        raise ValueError(f"Expected 3 Kusto result sets, got {len(frames)}")
    result = {name: frames[index] for index, name in enumerate(RESULT_SET_NAMES)}
    for name, frame in result.items():
        frame.to_csv(paths[name], index=False)
        print(f"[cache-write] {RESULT_SET_LABELS[name]}: {paths[name]}")
    return result


def normalize_frames(data: dict[str, Any]) -> dict[str, Any]:
    pd = ensure_pandas()
    date_columns = [
        "OriginalCreateDate",
        "ModifiedDate",
        "MitigateDate",
        "ResolveDate",
        "FirstAutoTransferAt",
        "FirstAutoLinkAt",
        "FirstManualTransferAt",
        "FirstManualRelationshipUpdateAt",
        "FirstAutoActionAt",
    ]
    normalized = {}
    for name, frame in data.items():
        if frame is None or frame.empty:
            normalized[name] = pd.DataFrame()
            continue
        copy_frame = frame.copy()
        for column in date_columns:
            if column in copy_frame.columns:
                copy_frame[column] = pd.to_datetime(copy_frame[column], errors="coerce", utc=True).dt.tz_convert(None)
        normalized[name] = copy_frame
    return normalized


def text_value(value: Any, default: str = "") -> str:
    pd = runner_report.pd
    if value is None:
        return default
    if pd is not None and pd.isna(value):
        return default
    text = str(value).strip()
    if text.lower() in {"", "nan", "nat", "none"}:
        return default
    return text


def html_text(value: Any, default: str = "") -> str:
    return html.escape(text_value(value, default))


def truncate_text(value: Any, limit: int = 150) -> str:
    text = re.sub(r"\s+", " ", text_value(value)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def numeric(value: Any) -> float | None:
    pd = runner_report.pd
    if value is None:
        return None
    if pd is not None and pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def int_count(frame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(runner_report.pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def count_eq(frame, column: str, value: int) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int((runner_report.pd.to_numeric(frame[column], errors="coerce") == value).sum())


def flag_eq(frame, column: str, value: int):
    pd = runner_report.pd
    if frame.empty:
        return pd.Series([], dtype=bool)
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return (pd.to_numeric(frame[column], errors="coerce") == value).fillna(False)


def rework_mask(frame):
    if frame.empty:
        return runner_report.pd.Series([], dtype=bool)
    return (flag_eq(frame, "AutoTransferCorrect", 0) | flag_eq(frame, "AutoLinkCorrect", 0)).fillna(False)


def rework_count(frame) -> int:
    if frame.empty:
        return 0
    return int(rework_mask(frame).sum())


def ratio(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return part / total


def pct_text(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def whole_number_text(value: Any, default: str = "0") -> str:
    number = numeric(value)
    if number is None:
        return html_text(value, default)
    return f"{number:.0f}"


def pp_delta(current: float | None, previous: float | None) -> str:
    if current is None or previous is None:
        return "-"
    return f"{(current - previous) * 100:+.1f}pp"


def count_delta(current: int, previous: int) -> str:
    return f"{current - previous:+d}"


def seconds_label(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def percentile_seconds(frame, column: str, percentile: float) -> float | None:
    pd = runner_report.pd
    if frame.empty or column not in frame.columns:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.quantile(percentile))


def filter_period(frame, start_date: date, end_exclusive: date):
    if frame.empty or "OriginalCreateDate" not in frame.columns:
        return frame.iloc[0:0].copy()
    start_time = datetime.combine(start_date, time.min)
    end_time = datetime.combine(end_exclusive, time.min)
    mask = (frame["OriginalCreateDate"] >= start_time) & (frame["OriginalCreateDate"] < end_time)
    return frame.loc[mask].copy()


def build_period_metrics(frame) -> dict[str, Any]:
    eligible = len(frame)
    auto_transfer = count_eq(frame, "HasAutoTransfer", 1)
    auto_link = count_eq(frame, "HasAutoLink", 1)
    auto_any = count_eq(frame, "HasAnyAutoAction", 1)
    transfer_correct = count_eq(frame, "AutoTransferCorrect", 1)
    transfer_incorrect = count_eq(frame, "AutoTransferCorrect", 0)
    link_correct = count_eq(frame, "AutoLinkCorrect", 1)
    link_incorrect = count_eq(frame, "AutoLinkCorrect", 0)
    rework = rework_count(frame)
    manual_transfer_after_auto = count_eq(frame, "HasManualTransferAfterAuto", 1)
    manual_relationship_after_auto = count_eq(frame, "HasManualRelationshipUpdateAfterAuto", 1)
    return {
        "eligible": eligible,
        "auto_transfer": auto_transfer,
        "auto_link": auto_link,
        "auto_any": auto_any,
        "transfer_correct": transfer_correct,
        "transfer_incorrect": transfer_incorrect,
        "link_correct": link_correct,
        "link_incorrect": link_incorrect,
        "rework": rework,
        "manual_transfer_after_auto": manual_transfer_after_auto,
        "manual_relationship_after_auto": manual_relationship_after_auto,
        "auto_transfer_coverage": ratio(auto_transfer, eligible),
        "auto_link_coverage": ratio(auto_link, eligible),
        "auto_any_coverage": ratio(auto_any, eligible),
        "transfer_correctness": ratio(transfer_correct, auto_transfer),
        "link_correctness": ratio(link_correct, auto_link),
        "rework_rate": ratio(rework, auto_any),
        "first_auto_p50": percentile_seconds(frame, "FirstAutoActionLatencySeconds", 0.50),
        "first_auto_p95": percentile_seconds(frame, "FirstAutoActionLatencySeconds", 0.95),
        "transfer_p50": percentile_seconds(frame, "TransferLatencySeconds", 0.50),
        "link_p50": percentile_seconds(frame, "LinkLatencySeconds", 0.50),
    }


def badge(label: str, css_class: str) -> str:
    return f'<span class="badge {css_class}">{html.escape(label)}</span>'


def higher_rate_status(value: float | None, target_pct: float) -> str:
    if value is None:
        return badge("no data", "gray")
    target = target_pct / 100
    if value >= target:
        return badge("on target", "green")
    if value >= max(0.0, target - 0.15):
        return badge("trending", "yellow")
    return badge("in focus", "red")


def lower_rate_status(value: float | None, target_pct: float) -> str:
    if value is None:
        return badge("no data", "gray")
    target = target_pct / 100
    if value <= target:
        return badge("on target", "green")
    if value <= target + 0.10:
        return badge("watch", "yellow")
    return badge("in focus", "red")


def latency_status(seconds: float | None, target_minutes: float) -> str:
    if seconds is None:
        return badge("no data", "gray")
    target_seconds = target_minutes * 60
    if seconds <= target_seconds:
        return badge("on target", "green")
    if seconds <= target_seconds * 2:
        return badge("watch", "yellow")
    return badge("in focus", "red")


def table(headers: list[str], rows: list[list[str]], row_classes: list[str] | None = None) -> str:
    header_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body_rows = []
    for index, row in enumerate(rows):
        css_class = f' class="{row_classes[index]}"' if row_classes and row_classes[index] else ""
        body_rows.append(f"<tr{css_class}>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    if not body_rows:
        body_rows.append(f"<tr><td colspan=\"{len(headers)}\">No data for this period</td></tr>")
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def column_definitions(key: str) -> str:
    definitions = COLUMN_DEFINITIONS.get(key, [])
    if not definitions:
        return ""
    rows = "".join(
        f"<dt>{html.escape(column)}</dt><dd>{html.escape(description)}</dd>"
        for column, description in definitions
    )
    return f'<div class="column-definitions"><div class="definition-title">Column definitions</div><dl>{rows}</dl></div>'


def icm_anchor(incident_id: Any, link: Any = None) -> str:
    incident_text = text_value(incident_id)
    if not incident_text:
        return "&mdash;"
    link_text = text_value(link) or f"https://portal.microsofticm.com/imp/v5/incidents/details/{incident_text}/summary"
    return f'<a href="{html.escape(link_text, quote=True)}" target="_blank">{html.escape(incident_text)}</a>'


def format_datetime_cell(value: Any) -> str:
    pd = runner_report.pd
    if value is None or (pd is not None and pd.isna(value)):
        return "-"
    if hasattr(value, "strftime"):
        return html.escape(value.strftime("%Y-%m-%d %H:%M"))
    return html_text(value, "-")


def overview_table(previous: dict[str, Any], current: dict[str, Any], args: argparse.Namespace) -> str:
    rows = [
        [
            "Auto action coverage",
            f"&gt; {args.coverage_target:.0f}%",
            pct_text(previous["auto_any_coverage"]),
            f'<span class="metric-current">{pct_text(current["auto_any_coverage"])}</span>',
            pp_delta(current["auto_any_coverage"], previous["auto_any_coverage"]),
            higher_rate_status(current["auto_any_coverage"], args.coverage_target),
        ],
        [
            "Transfer correctness",
            f"&gt; {args.correctness_target:.0f}%",
            pct_text(previous["transfer_correctness"]),
            f'<span class="metric-current">{pct_text(current["transfer_correctness"])}</span>',
            pp_delta(current["transfer_correctness"], previous["transfer_correctness"]),
            higher_rate_status(current["transfer_correctness"], args.correctness_target),
        ],
        [
            "Link correctness",
            f"&gt; {args.correctness_target:.0f}%",
            pct_text(previous["link_correctness"]),
            f'<span class="metric-current">{pct_text(current["link_correctness"])}</span>',
            pp_delta(current["link_correctness"], previous["link_correctness"]),
            higher_rate_status(current["link_correctness"], args.correctness_target),
        ],
        [
            "Rework rate",
            f"&lt; {args.rework_target:.0f}%",
            pct_text(previous["rework_rate"]),
            f'<span class="metric-current">{pct_text(current["rework_rate"])}</span>',
            pp_delta(current["rework_rate"], previous["rework_rate"]),
            lower_rate_status(current["rework_rate"], args.rework_target),
        ],
        [
            "First auto action p50",
            f"&lt; {args.latency_target_minutes:.0f}m",
            seconds_label(previous["first_auto_p50"]),
            f'<span class="metric-current">{seconds_label(current["first_auto_p50"])}</span>',
            "-" if current["first_auto_p50"] is None or previous["first_auto_p50"] is None else seconds_label(current["first_auto_p50"] - previous["first_auto_p50"]),
            latency_status(current["first_auto_p50"], args.latency_target_minutes),
        ],
    ]
    return table(["KPI", "Report Target", "Previous", "Current", "Delta", "Status"], rows)


def monthly_summary_table(window: KpiWindow, previous: dict[str, Any], current: dict[str, Any]) -> str:
    rows = []
    for label, metrics, is_current in [(window.previous_label, previous, False), (window.current_label, current, True)]:
        coverage = pct_text(metrics["auto_any_coverage"])
        coverage_cell = f'<span class="metric-current">{coverage}</span>' if is_current else coverage
        rows.append([
            html.escape(label),
            str(metrics["eligible"]),
            str(metrics["auto_transfer"]),
            str(metrics["auto_link"]),
            str(metrics["auto_any"]),
            coverage_cell,
            pct_text(metrics["transfer_correctness"]),
            pct_text(metrics["link_correctness"]),
            str(metrics["rework"]),
            pct_text(metrics["rework_rate"]),
            seconds_label(metrics["first_auto_p50"]),
            seconds_label(metrics["first_auto_p95"]),
        ])
    return table(
        ["Month", "Eligible", "Auto transfers", "Auto links", "Any auto", "Coverage", "Transfer correct", "Link correct", "Rework", "Rework %", "First auto p50", "First auto p95"],
        rows,
    )


def definitions_table(window: KpiWindow, args: argparse.Namespace) -> str:
    full_window = f"{window.previous_start.isoformat()} to {(window.current_end_exclusive - timedelta(days=1)).isoformat()}"
    rows = [
        [
            "pp",
            "Percentage points. Example: if a KPI moves from 12.0% to 10.0%, the delta is -2.0pp. It is a direct subtraction of two percentages, not a relative percent change.",
        ],
        [
            "First auto p50",
            "Median time from incident creation to the first auto-triage action. The source KQL stores this in seconds as FirstAutoActionLatencySeconds. The HTML converts seconds to a readable unit, so 2.2m means 2.2 minutes.",
        ],
        [
            "Latency",
            "FirstAutoActionAt is the earlier of first auto transfer and first auto link. Latency is datetime_diff('second', FirstAutoActionAt, OriginalCreateDate). Transfer and link latency use the same calculation with FirstAutoTransferAt or FirstAutoLinkAt.",
        ],
        [
            "Team / Overall window",
            f"TeamLevelKpi and OverallKpi cover the rendered report window: {html.escape(full_window)}. For this report that is previous month plus current month, not the source query's original 90-day lookback.",
        ],
        [
            "Report targets",
            f"Targets are report-side defaults, not values from the KQL result sets: coverage {args.coverage_target:.0f}%, correctness {args.correctness_target:.0f}%, max rework {args.rework_target:.0f}%, and first-auto-action p50 latency {args.latency_target_minutes:.0f} minutes. They can be changed with CLI flags such as --coverage-target.",
        ],
        [
            "Rework",
            "A rework row is counted only when the matching auto action was later corrected: AutoTransferCorrect = 0 or AutoLinkCorrect = 0. This keeps rework consistent with the transfer/link correctness metrics.",
        ],
    ]
    return table(["Term", "Meaning"], rows)


def grouped_bar_svg(window: KpiWindow, previous: dict[str, Any], current: dict[str, Any]) -> str:
    width = 900
    height = 290
    left = 64
    top = 30
    chart_width = 790
    chart_height = 190
    bottom = top + chart_height
    metrics = [
        ("Any coverage", "auto_any_coverage", "higher"),
        ("Transfer correct", "transfer_correctness", "higher"),
        ("Link correct", "link_correctness", "higher"),
        ("Rework", "rework_rate", "lower"),
    ]
    slot = chart_width / len(metrics)
    bar_width = 34
    parts = [f'<svg class="report-chart" width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
    for step in range(0, 101, 25):
        y_pos = bottom - step / 100 * chart_height
        parts.append(f'<line x1="{left}" y1="{y_pos:.1f}" x2="{left + chart_width}" y2="{y_pos:.1f}" stroke="#eee" />')
        parts.append(f'<text x="{left - 8}" y="{y_pos + 4:.1f}" font-size="10" text-anchor="end" fill="#666">{step}%</text>')
    for index, (label, key, _) in enumerate(metrics):
        center = left + index * slot + slot / 2
        for month_index, (month_label_text, metrics_map, color) in enumerate([(window.previous_label, previous, "#a8a29e"), (window.current_label, current, "#0E2841")]):
            value = metrics_map[key]
            pct_value = 0 if value is None else max(0.0, min(1.0, value))
            bar_height = pct_value * chart_height
            x_pos = center - bar_width - 5 + month_index * (bar_width + 10)
            y_pos = bottom - bar_height
            parts.append(f'<rect x="{x_pos:.1f}" y="{y_pos:.1f}" width="{bar_width}" height="{bar_height:.1f}" fill="{color}" />')
            parts.append(f'<text x="{x_pos + bar_width / 2:.1f}" y="{max(top + 12, y_pos - 5):.1f}" font-size="10" text-anchor="middle" fill="#0E2841" font-weight="600">{pct_text(value)}</text>')
        parts.append(f'<text x="{center:.1f}" y="{bottom + 22}" font-size="11" text-anchor="middle" fill="#444">{html.escape(label)}</text>')
    parts.append('<rect x="64" y="256" width="14" height="14" fill="#a8a29e" /><text x="84" y="267" font-size="12" fill="#444">Previous</text>')
    parts.append('<rect x="180" y="256" width="14" height="14" fill="#0E2841" /><text x="200" y="267" font-size="12" fill="#444">Current</text>')
    parts.append("</svg>")
    return '<div class="chart-wrap">' + "".join(parts) + "</div>"


def latency_svg(window: KpiWindow, previous: dict[str, Any], current: dict[str, Any]) -> str:
    values = [previous["first_auto_p50"], previous["first_auto_p95"], current["first_auto_p50"], current["first_auto_p95"]]
    max_seconds = max([value for value in values if value is not None] + [60])
    width = 900
    height = 230
    left = 140
    chart_width = 610
    row_height = 42
    labels = [
        (f"{window.previous_label} p50", previous["first_auto_p50"], "#a8a29e"),
        (f"{window.previous_label} p95", previous["first_auto_p95"], "#d4a72c"),
        (f"{window.current_label} p50", current["first_auto_p50"], "#0E2841"),
        (f"{window.current_label} p95", current["first_auto_p95"], "#156082"),
    ]
    parts = [f'<svg class="report-chart" width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">']
    for index, (label, value, color) in enumerate(labels):
        y_pos = 32 + index * row_height
        parts.append(f'<text x="{left - 12}" y="{y_pos + 17}" font-size="12" text-anchor="end" fill="#1a1a1a" font-weight="600">{html.escape(label)}</text>')
        if value is None:
            parts.append(f'<text x="{left}" y="{y_pos + 17}" font-size="12" fill="#6e7781">No data</text>')
            continue
        bar_width = value / max_seconds * chart_width
        parts.append(f'<rect x="{left}" y="{y_pos}" width="{bar_width:.1f}" height="24" fill="{color}" />')
        parts.append(f'<text x="{left + bar_width + 8:.1f}" y="{y_pos + 17}" font-size="12" fill="#444">{seconds_label(value)}</text>')
    parts.append("</svg>")
    return '<div class="chart-wrap">' + "".join(parts) + "</div>"


def overall_rollup_table(overall_frame) -> str:
    if overall_frame.empty:
        return table(["Metric", "Value"], [])
    row = overall_frame.iloc[0]
    metric_rows = [
        ["Eligible incidents", whole_number_text(row.get("EligibleIncidentCount"), "0")],
        ["Auto transfers", whole_number_text(row.get("AutoTransferCount"), "0")],
        ["Auto links", whole_number_text(row.get("AutoLinkCount"), "0")],
        ["Any auto action", whole_number_text(row.get("AutoAnyActionCount"), "0")],
        ["Auto transfer coverage", pct_text(numeric(row.get("AutoTransferCoveragePct")))],
        ["Auto link coverage", pct_text(numeric(row.get("AutoLinkCoveragePct")))],
        ["Any auto coverage", pct_text(numeric(row.get("AutoAnyCoveragePct")))],
        ["Transfer correctness", pct_text(numeric(row.get("AutoTransferCorrectnessPct")))],
        ["Link correctness", pct_text(numeric(row.get("AutoLinkCorrectnessPct")))],
        ["Rework count", whole_number_text(row.get("ReworkCount"), "0")],
        ["Rework rate", pct_text(numeric(row.get("ReworkRatePct")))],
        ["Manual transfer after first auto (broad)", whole_number_text(row.get("ManualTransferAfterAutoCount"), "0")],
        ["Manual relationship update after first auto (broad)", whole_number_text(row.get("ManualRelationshipUpdateAfterAutoCount"), "0")],
        ["First auto action p50", seconds_label(numeric(row.get("FirstAutoActionLatencyP50Sec")))],
        ["First auto action p95", seconds_label(numeric(row.get("FirstAutoActionLatencyP95Sec")))],
    ]
    return table(["Metric", "Value"], metric_rows)


def team_rollup_table(team_frame) -> str:
    if team_frame.empty:
        return table(["Original Team", "Eligible", "Any Auto", "Coverage", "Transfer Correct", "Link Correct", "Rework", "First Auto P50", "First Auto P95"], [])
    work = team_frame.copy().sort_values("OriginalOwningTeamName") if "OriginalOwningTeamName" in team_frame.columns else team_frame.copy()
    rows = []
    row_classes = []
    for _, row in work.iterrows():
        rework_rate = numeric(row.get("ReworkRatePct"))
        any_coverage = numeric(row.get("AutoAnyCoveragePct"))
        rows.append([
            html_text(row.get("OriginalOwningTeamName"), "Unknown"),
            html_text(row.get("EligibleIncidentCount"), "0"),
            html_text(row.get("AutoAnyActionCount"), "0"),
            pct_text(any_coverage),
            pct_text(numeric(row.get("AutoTransferCorrectnessPct"))),
            pct_text(numeric(row.get("AutoLinkCorrectnessPct"))),
            pct_text(rework_rate),
            seconds_label(numeric(row.get("FirstAutoActionLatencyP50Sec"))),
            seconds_label(numeric(row.get("FirstAutoActionLatencyP95Sec"))),
        ])
        if rework_rate is not None and rework_rate > 0.20:
            row_classes.append("row-focus")
        elif any_coverage is None or any_coverage == 0:
            row_classes.append("row-muted")
        elif any_coverage < 0.50:
            row_classes.append("row-watch")
        else:
            row_classes.append("")
    return table(["Original Team", "Eligible", "Any Auto", "Coverage", "Transfer Correct", "Link Correct", "Rework", "First Auto P50", "First Auto P95"], rows, row_classes)


def team_color_legend() -> str:
    return table(
        ["Row color", "Meaning"],
        [
            ["Red", "Rework rate is greater than 20% for that original owning team."],
            ["Yellow", "Auto-action coverage is below 50%, but the team has at least one auto action."],
            ["Gray", "No auto action was found for that team's eligible incidents."],
            ["No fill", "No row-level warning condition was applied."],
        ],
        ["row-focus", "row-watch", "row-muted", ""],
    )


def rework_rows(frame):
    if frame.empty:
        return frame.iloc[0:0].copy()
    return frame.loc[rework_mask(frame)].copy()


def correction_type(row) -> str:
    correction_bits = []
    if numeric(row.get("AutoTransferCorrect")) == 0:
        correction_bits.append("transfer")
    if numeric(row.get("AutoLinkCorrect")) == 0:
        correction_bits.append("relationship")
    return ", ".join(correction_bits) or "manual correction"


def csv_datetime(value: Any) -> str:
    pd = runner_report.pd
    if value is None or (pd is not None and pd.isna(value)):
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ")
    return text_value(value)


def rework_export_frame(frame):
    pd = runner_report.pd
    work = rework_rows(frame)
    columns = ["IncidentId", "IncidentLink", "OriginalCreateDate", "OriginalOwningTeamName", "CurrentOwningTeamName", "ManualCorrection", "FirstAutoActionAt", "FirstAutoActionLatencySeconds", "OriginalTitle"]
    if work.empty:
        return pd.DataFrame(columns=columns)
    if "OriginalCreateDate" in work.columns:
        work = work.sort_values("OriginalCreateDate", ascending=False)
    rows = []
    for _, row in work.iterrows():
        rows.append({
            "IncidentId": text_value(row.get("IncidentId")),
            "IncidentLink": text_value(row.get("IncidentLink")),
            "OriginalCreateDate": csv_datetime(row.get("OriginalCreateDate")),
            "OriginalOwningTeamName": text_value(row.get("OriginalOwningTeamName"), "Unknown"),
            "CurrentOwningTeamName": text_value(row.get("CurrentOwningTeamName"), "Unknown"),
            "ManualCorrection": correction_type(row),
            "FirstAutoActionAt": csv_datetime(row.get("FirstAutoActionAt")),
            "FirstAutoActionLatencySeconds": text_value(row.get("FirstAutoActionLatencySeconds")),
            "OriginalTitle": text_value(row.get("OriginalTitle")),
        })
    return pd.DataFrame(rows, columns=columns)


def write_rework_details_csv(frame, path: Path) -> int:
    export_frame = rework_export_frame(frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    export_frame.to_csv(path, index=False)
    return len(export_frame)


def rework_detail_table(frame, limit: int = 20) -> str:
    if frame.empty:
        return table(["Incident", "Created", "Original Team", "Current Team", "Manual Correction", "First Auto", "Title"], [])
    work = rework_rows(frame)
    if work.empty:
        return table(["Incident", "Created", "Original Team", "Current Team", "Manual Correction", "First Auto", "Title"], [])
    work = work.sort_values("OriginalCreateDate", ascending=False)
    if limit > 0:
        work = work.head(limit)
    rows = []
    for _, row in work.iterrows():
        rows.append([
            icm_anchor(row.get("IncidentId"), row.get("IncidentLink")),
            format_datetime_cell(row.get("OriginalCreateDate")),
            html_text(row.get("OriginalOwningTeamName"), "Unknown"),
            html_text(row.get("CurrentOwningTeamName"), "Unknown"),
            html.escape(correction_type(row)),
            format_datetime_cell(row.get("FirstAutoActionAt")),
            html.escape(truncate_text(row.get("OriginalTitle"), 180)),
        ])
    return table(["Incident", "Created", "Original Team", "Current Team", "Manual Correction", "First Auto", "Title"], rows, ["row-focus"] * len(rows))


def incident_row_class(row) -> str:
    has_auto = numeric(row.get("HasAnyAutoAction")) == 1
    has_rework = numeric(row.get("HasAnyManualCorrectionAfterAuto")) == 1
    transfer_bad = numeric(row.get("AutoTransferCorrect")) == 0
    link_bad = numeric(row.get("AutoLinkCorrect")) == 0
    if has_rework or transfer_bad or link_bad:
        return "row-focus"
    if not has_auto:
        return "row-muted"
    return "row-good"


def incident_detail_table(frame, limit: int) -> str:
    if frame.empty:
        return table(["Incident", "Created", "Original Team", "Current Team", "Sev", "Auto Transfer", "Auto Link", "Correct", "Rework", "First Auto", "Latency", "Title"], [])
    work = frame.copy().sort_values("OriginalCreateDate") if "OriginalCreateDate" in frame.columns else frame.copy()
    if limit > 0:
        work = work.head(limit)
    rows = []
    classes = []
    for _, row in work.iterrows():
        transfer_correct = numeric(row.get("AutoTransferCorrect"))
        link_correct = numeric(row.get("AutoLinkCorrect"))
        correct_bits = []
        if transfer_correct is not None:
            correct_bits.append("transfer yes" if transfer_correct == 1 else "transfer no")
        if link_correct is not None:
            correct_bits.append("link yes" if link_correct == 1 else "link no")
        rows.append([
            icm_anchor(row.get("IncidentId"), row.get("IncidentLink")),
            format_datetime_cell(row.get("OriginalCreateDate")),
            html_text(row.get("OriginalOwningTeamName"), "Unknown"),
            html_text(row.get("CurrentOwningTeamName"), "Unknown"),
            html_text(row.get("OriginalSeverity"), "-"),
            "Yes" if numeric(row.get("HasAutoTransfer")) == 1 else "No",
            "Yes" if numeric(row.get("HasAutoLink")) == 1 else "No",
            html.escape(", ".join(correct_bits) or "-") ,
            "Yes" if numeric(row.get("HasAnyManualCorrectionAfterAuto")) == 1 else "No",
            format_datetime_cell(row.get("FirstAutoActionAt")),
            seconds_label(numeric(row.get("FirstAutoActionLatencySeconds"))),
            html.escape(truncate_text(row.get("OriginalTitle"), 220)),
        ])
        classes.append(incident_row_class(row))
    return table(["Incident", "Created", "Original Team", "Current Team", "Sev", "Auto Transfer", "Auto Link", "Correct", "Rework", "First Auto", "Latency", "Title"], rows, classes)


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def safe_label(label: str) -> str:
    return label.replace("/", "-").replace("..", "_")


def rework_details_csv_path(out_path: Path, window: KpiWindow) -> Path:
    return out_path.with_name(f"auto-triage-rework-details-{safe_label(window.current_label)}.csv")


def apply_report_rework_to_team_frame(team_frame, incident_frame):
    pd = runner_report.pd
    if team_frame.empty or incident_frame.empty or "OriginalOwningTeamName" not in team_frame.columns or "OriginalOwningTeamName" not in incident_frame.columns:
        return team_frame
    work = incident_frame.copy()
    work["_ReportRework"] = rework_mask(work).astype(int)
    summary = work.groupby("OriginalOwningTeamName", dropna=False)["_ReportRework"].sum().reset_index(name="_ReportReworkCount")
    result = team_frame.copy().merge(summary, on="OriginalOwningTeamName", how="left")
    result["ReworkCount"] = pd.to_numeric(result["_ReportReworkCount"], errors="coerce").fillna(0).astype(int)
    if "AutoAnyActionCount" in result.columns:
        auto_any = pd.to_numeric(result["AutoAnyActionCount"], errors="coerce")
    else:
        auto_any = pd.Series(0, index=result.index)
    result["ReworkRatePct"] = result["ReworkCount"] / auto_any.where(auto_any > 0)
    return result.drop(columns=["_ReportReworkCount"])


def apply_report_rework_to_overall_frame(overall_frame, incident_frame):
    if overall_frame.empty or incident_frame.empty:
        return overall_frame
    result = overall_frame.copy()
    rework = rework_count(incident_frame)
    auto_any = count_eq(incident_frame, "HasAnyAutoAction", 1)
    result.loc[:, "ReworkCount"] = rework
    result.loc[:, "ReworkRatePct"] = ratio(rework, auto_any)
    return result


def build_html(data: dict[str, Any], window: KpiWindow, args: argparse.Namespace) -> str:
    incident_frame = data.get("incident_level", runner_report.pd.DataFrame())
    team_frame = apply_report_rework_to_team_frame(data.get("team_level", runner_report.pd.DataFrame()), incident_frame)
    overall_frame = apply_report_rework_to_overall_frame(data.get("overall", runner_report.pd.DataFrame()), incident_frame)
    previous_frame = filter_period(incident_frame, window.previous_start, window.previous_end_exclusive)
    current_frame = filter_period(incident_frame, window.current_start, window.current_end_exclusive)
    previous_metrics = build_period_metrics(previous_frame)
    current_metrics = build_period_metrics(current_frame)
    caches = cache_paths(args.cache_dir, window)
    generated_at = datetime.now().replace(microsecond=0).isoformat()
    rendered_kql = relative_path(args.render_kql) if args.render_kql else "not written"
    title = f"Runner Auto-Triage KPI Report - {window.previous_label} vs {window.current_label}"
    rework_csv_path = rework_details_csv_path(args.out, window)
    rework_csv_link = html.escape(rework_csv_path.name, quote=True)
    rework_count = len(rework_rows(incident_frame))
    visible_rework_count = min(20, rework_count)

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
    <h1>Auto-Triage KPI</h1>
    <div class="meta">{html.escape(window.previous_label)} vs {html.escape(window.current_label)}<br>{html.escape(generated_at)}</div>
        <a href="#overview">1. Overview</a>
        <a href="#definitions">2. KPI Definitions</a>
        <a href="#summary">3. Monthly Summary</a>
        <a href="#teams">4. Team Rollup</a>
        <a href="#overall">5. Overall Rollup</a>
        <a href="#rework">6. Rework Details</a>
        <a href="#notes">7. Notes</a>
  </nav>
  <main class="content">
        <h2 id="overview">1. Status Overview</h2>
        <p>Auto-triage quality for eligible Sev2/2.5 incidents originally created in target teams. Current period {html.escape(window.current_display_range)} is compared with {html.escape(window.previous_display_range)}. Deltas shown as <code>pp</code> are percentage-point changes.</p>
        {column_definitions("overview")}
    {overview_table(previous_metrics, current_metrics, args)}

        <h2 id="definitions">2. KPI Definitions</h2>
        {column_definitions("definitions")}
        {definitions_table(window, args)}

        <h2 id="summary">3. Monthly Summary</h2>
        {column_definitions("monthly_summary")}
    {monthly_summary_table(window, previous_metrics, current_metrics)}
    {grouped_bar_svg(window, previous_metrics, current_metrics)}
    <h3>Latency</h3>
        <p>The latency chart uses the incident-level first-auto-action latency for each month and displays p50/p95 as readable time labels.</p>
    {latency_svg(window, previous_metrics, current_metrics)}

        <h2 id="teams">4. RESULT SET 2 - Team-Level KPI Rollup</h2>
        <p>This section uses the query's <code>TeamLevelKpi</code> result set for the team rollup and recalculates displayed <code>Rework</code> from <code>IncidentLevelKpi</code> so it matches correctness logic. <code>Rework</code> is <code>ReworkCount / AutoAnyActionCount</code>, where <code>ReworkCount</code> means the matching auto action was later corrected: <code>AutoTransferCorrect = 0</code> or <code>AutoLinkCorrect = 0</code>.</p>
        <h3>Row Color Legend</h3>
        {column_definitions("row_color_legend")}
        {team_color_legend()}
        <h3>Team KPI Rollup</h3>
        {column_definitions("team_rollup")}
    {team_rollup_table(team_frame)}

        <h2 id="overall">5. RESULT SET 3 - Overall KPI Rollup</h2>
        <p>This section uses the query's <code>OverallKpi</code> result set for the full rendered report window. Displayed rework count/rate is recalculated from <code>IncidentLevelKpi</code> so it stays consistent with correctness.</p>
        {column_definitions("overall_rollup")}
        {overall_rollup_table(overall_frame)}

        <h2 id="rework">6. Manual Correction / Rework Details</h2>
        <p>Rows where the matching auto action was later corrected: <code>AutoTransferCorrect = 0</code> or <code>AutoLinkCorrect = 0</code>. Showing newest {visible_rework_count} of {rework_count} rows. <a href="{rework_csv_link}" target="_blank">Open the full CSV list</a>.</p>
        {column_definitions("rework_details")}
        {rework_detail_table(incident_frame, 20)}

        <h2 id="notes">7. Notes</h2>
    <div class="notes">
      <ul>
        <li>Source KQL: <code>{html.escape(relative_path(args.kql))}</code></li>
        <li>Rendered KQL: <code>{html.escape(rendered_kql)}</code></li>
        <li>Incident cache: <code>{html.escape(relative_path(caches["incident_level"]))}</code></li>
        <li>Team cache: <code>{html.escape(relative_path(caches["team_level"]))}</code></li>
        <li>Overall cache: <code>{html.escape(relative_path(caches["overall"]))}</code></li>
        <li>Full rework detail CSV: <code>{html.escape(relative_path(rework_csv_path))}</code></li>
        <li>Abbreviations: <code>KPI</code> = Key Performance Indicator; <code>pp</code> = percentage points; <code>p50</code> = 50th percentile / median; <code>p95</code> = 95th percentile; <code>s</code>, <code>m</code>, <code>h</code>, and <code>d</code> = seconds, minutes, hours, and days; <code>auto</code> = auto-triage action.</li>
        <li>The renderer bounds <code>lookBackRange</code> to the previous-period start and adds <code>reportEndTime</code> to incident create/history filters, so all three result sets cover the same report window.</li>
        <li>Displayed rework rates use matching-action correctness flags, not the broader manual-after-first-auto support fields.</li>
                <li><code>IncidentLevelKpi</code> is still queried and cached because Overview, Monthly Summary, latency, and rework details are calculated from it. The full incident-level table is intentionally not rendered in the HTML.</li>
        <li>Correctness follows the source query: later manual transfer after auto transfer means transfer incorrect; later manual relationship update after auto link means link incorrect.</li>
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
        args.out = DEFAULT_OUTPUT_DIR / f"auto-triage-kpi-{window.current_label}.html".replace("/", "-").replace("..", "_")
    query_text = render_kql(args.kql, window)
    if args.render_kql:
        args.render_kql.parent.mkdir(parents=True, exist_ok=True)
        args.render_kql.write_text(query_text, encoding="utf-8")
        print(f"[render-kql] {args.render_kql}")
    raw_data = load_or_query(args, window, query_text)
    data = normalize_frames(raw_data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rework_csv_path = rework_details_csv_path(args.out, window)
    rework_count = write_rework_details_csv(data.get("incident_level", runner_report.pd.DataFrame()), rework_csv_path)
    print(f"[rework-csv] {rework_csv_path} ({rework_count} rows)")
    args.out.write_text(build_html(data, window, args), encoding="utf-8")
    print(f"[html] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())