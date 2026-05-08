from __future__ import annotations

import argparse
import importlib
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.yaml"
DEFAULT_CACHE_DIR = SCRIPT_DIR / "output" / "cache"
DEFAULT_ASSET_DIR = SCRIPT_DIR / "output" / "assets"

pd = None
plt = None
Inches = None
Pt = None
RGBColor = None
PP_ALIGN = None
MSO_ANCHOR = None
MSO_SHAPE = None
Presentation = None

TEXT_COLOR = (34, 40, 49)
MUTED_TEXT = (91, 103, 117)
GRID_COLOR = (223, 228, 234)
HEADER_FILL = (32, 82, 122)
LIGHT_FILL = (244, 247, 250)
ACCENT_BLUE = (41, 105, 176)
ACCENT_GREEN = (47, 128, 95)
ACCENT_ORANGE = (200, 112, 44)
ACCENT_RED = (174, 63, 67)
ACCENT_TEAL = (37, 130, 141)
CHART_COLORS = ["#2969b0", "#2f805f", "#c8702c", "#ae3f43", "#25828d", "#6b7280"]
PROACTIVE_SUCCESS_RESULTS = {"Completed", "Incompleted"}
PROACTIVE_RESULT_LABELS = {
    "Completed": "Linked",
    "Incompleted": "Found parent",
    "ProactiveFailed": "Failure - others",
    "DatabaseDown": "Failure - database down",
    "NotLinked": "Not linked",
}


@dataclass(frozen=True)
class ReportWindow:
    start_date: date
    end_date: date
    start_time: datetime
    end_time_exclusive: datetime
    previous_start_time: datetime
    previous_end_time: datetime
    trend_start_time: datetime
    query_start_time: datetime

    @property
    def display_range(self) -> str:
        return f"{self.start_date.isoformat()} to {self.end_date.isoformat()}"

    @property
    def previous_display_range(self) -> str:
        previous_end_inclusive = (self.previous_end_time - timedelta(days=1)).date()
        return f"{self.previous_start_time.date().isoformat()} to {previous_end_inclusive.isoformat()}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Runner Review PowerPoint report from KQL data.")
    parser.add_argument("--start", required=True, help="Inclusive start date, for example 2026-04-15.")
    parser.add_argument("--end", required=True, help="Inclusive end date, for example 2026-04-30.")
    parser.add_argument("--out", type=Path, help="PowerPoint output path. Defaults to report/output/runner-review-START-END.pptx.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to config.yaml.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Directory for cached CSV query results.")
    parser.add_argument("--trend-days", type=int, default=None, help="Trend lookback days. Defaults to config report.default_trend_days.")
    parser.add_argument("--query", action="append", help="Run only the named query. Can be specified multiple times.")
    parser.add_argument("--use-cache", action="store_true", help="Use a cached CSV when present instead of querying Kusto.")
    parser.add_argument("--cache-only", action="store_true", help="Do not query Kusto. Missing caches become empty datasets.")
    parser.add_argument("--strict", action="store_true", help="Fail immediately if a live Kusto query fails.")
    parser.add_argument("--auth", choices=["interactive", "device", "azcli", "msi"], default="interactive", help="Kusto authentication mode.")
    parser.add_argument("--render-kql", type=Path, help="Write rendered KQL files to this directory.")
    parser.add_argument("--render-only", action="store_true", help="Render KQL and exit without querying or creating a deck.")
    return parser.parse_args()


def require_module(import_name: str, package_name: str):
    try:
        return importlib.import_module(import_name)
    except ImportError as error:
        raise SystemExit(
            f"Missing dependency '{package_name}'. Install report dependencies with: "
            f'"{sys.executable}" -m pip install -r "{SCRIPT_DIR / "requirements.txt"}"'
        ) from error


def load_config(config_path: Path) -> dict[str, Any]:
    yaml_module = require_module("yaml", "PyYAML")
    with config_path.open("r", encoding="utf-8") as config_file:
        loaded = yaml_module.safe_load(config_file)
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file is empty or invalid: {config_path}")
    return loaded


def initialize_data_modules() -> None:
    global pd, plt
    pd = require_module("pandas", "pandas")
    matplotlib = require_module("matplotlib", "matplotlib")
    matplotlib.use("Agg")
    plt = importlib.import_module("matplotlib.pyplot")


def initialize_ppt_modules() -> None:
    global Inches, Pt, RGBColor, PP_ALIGN, MSO_ANCHOR, MSO_SHAPE, Presentation
    presentation_module = require_module("pptx", "python-pptx")
    Presentation = presentation_module.Presentation
    Inches = importlib.import_module("pptx.util").Inches
    Pt = importlib.import_module("pptx.util").Pt
    RGBColor = importlib.import_module("pptx.dml.color").RGBColor
    PP_ALIGN = importlib.import_module("pptx.enum.text").PP_ALIGN
    MSO_ANCHOR = importlib.import_module("pptx.enum.text").MSO_ANCHOR
    MSO_SHAPE = importlib.import_module("pptx.enum.shapes").MSO_SHAPE


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM-DD date, got {value!r}") from error


def build_window(start_value: str, end_value: str, trend_days: int) -> ReportWindow:
    start_date = parse_iso_date(start_value)
    end_date = parse_iso_date(end_value)
    if end_date < start_date:
        raise ValueError("--end must be on or after --start")
    start_time = datetime.combine(start_date, time.min)
    end_time_exclusive = datetime.combine(end_date + timedelta(days=1), time.min)
    duration = end_time_exclusive - start_time
    previous_start_time = start_time - duration
    previous_end_time = start_time
    trend_start_time = end_time_exclusive - timedelta(days=trend_days)
    query_start_time = min(previous_start_time, trend_start_time)
    return ReportWindow(
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time_exclusive=end_time_exclusive,
        previous_start_time=previous_start_time,
        previous_end_time=previous_end_time,
        trend_start_time=trend_start_time,
        query_start_time=query_start_time,
    )


def kusto_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def dynamic_string(values: list[str]) -> str:
    quoted = ",".join(f"'{str(value)}'" for value in values)
    return f"dynamic([{quoted}])"


def build_template_params(config: dict[str, Any], window: ReportWindow) -> dict[str, str]:
    teams = config.get("teams", {})
    return {
        "QUERY_START_TIME": kusto_datetime(window.query_start_time),
        "CURRENT_START_TIME": kusto_datetime(window.start_time),
        "END_TIME": kusto_datetime(window.end_time_exclusive),
        "PREVIOUS_START_TIME": kusto_datetime(window.previous_start_time),
        "PREVIOUS_END_TIME": kusto_datetime(window.previous_end_time),
        "TREND_START_TIME": kusto_datetime(window.trend_start_time),
        "XINYAN_TEAM_IDS": dynamic_string(teams.get("xinyan_team_ids", [])),
        "ACK_TEAM_IDS": dynamic_string(teams.get("acknowledge_team_ids", [])),
        "RUNNER_TEAM_ID": str(teams.get("runner_team_id", "39447")),
    }


def render_template(template_path: Path, params: dict[str, str]) -> str:
    rendered = template_path.read_text(encoding="utf-8")
    for key, value in params.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    missing_tokens = sorted(set(re.findall(r"{{([A-Z0-9_]+)}}", rendered)))
    if missing_tokens:
        raise ValueError(f"Unresolved KQL template tokens in {template_path}: {', '.join(missing_tokens)}")
    return rendered


def selected_queries(config: dict[str, Any], query_names: list[str] | None) -> dict[str, dict[str, Any]]:
    queries = config.get("queries", {})
    if query_names:
        missing = [name for name in query_names if name not in queries]
        if missing:
            raise ValueError(f"Unknown query name(s): {', '.join(missing)}")
        return {name: queries[name] for name in query_names}
    return {name: query for name, query in queries.items() if query.get("enabled", False)}


def cache_path(cache_dir: Path, window: ReportWindow, trend_days: int, query_name: str) -> Path:
    file_name = f"{window.start_date.isoformat()}_{window.end_date.isoformat()}_trend{trend_days}_{query_name}.csv"
    return cache_dir / file_name


def execute_kusto_query(cluster_uri: str, database: str, query_text: str, auth_mode: str):
    kusto_data = require_module("azure.kusto.data", "azure-kusto-data")
    helper_module = require_module("azure.kusto.data.helpers", "azure-kusto-data")
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
        return pd.DataFrame()
    return helper_module.dataframe_from_result_table(response.primary_results[0])


def load_or_query_dataset(
    query_name: str,
    query_config: dict[str, Any],
    query_text: str,
    args: argparse.Namespace,
    window: ReportWindow,
    trend_days: int,
):
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    dataset_cache_path = cache_path(args.cache_dir, window, trend_days, query_name)
    if (args.use_cache or args.cache_only) and dataset_cache_path.exists():
        print(f"[cache] {query_name}: {dataset_cache_path}")
        return pd.read_csv(dataset_cache_path)
    if args.cache_only:
        print(f"[cache-miss] {query_name}: using empty dataset")
        return pd.DataFrame()
    print(f"[query] {query_name}: {query_config['cluster_uri']} / {query_config['database']}")
    try:
        frame = execute_kusto_query(query_config["cluster_uri"], query_config["database"], query_text, args.auth)
    except Exception as error:
        if args.strict:
            raise
        print(f"[query-error] {query_name}: {error}")
        return pd.DataFrame()
    frame.to_csv(dataset_cache_path, index=False)
    print(f"[cache-write] {query_name}: {dataset_cache_path}")
    return frame


def normalize_datetime_columns(frame, columns: list[str]):
    if frame.empty:
        return frame
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_datetime(result[column], errors="coerce", utc=True).dt.tz_convert(None)
    return result


def prepare_frames(data: dict[str, Any]) -> dict[str, Any]:
    date_columns = [
        "LookingDate",
        "CreateDate",
        "ModifiedDate",
        "MitigateDate",
        "ResolveDate",
        "AcknowledgeDate",
        "LinkedDate",
        "PreciseTimeStamp",
        "StartOfWeek",
    ]
    return {name: normalize_datetime_columns(frame, date_columns) for name, frame in data.items()}


def filter_period(frame, date_column: str, start_time: datetime, end_time: datetime):
    if frame.empty or date_column not in frame.columns:
        return frame.iloc[0:0].copy()
    mask = (frame[date_column] >= start_time) & (frame[date_column] < end_time)
    return frame.loc[mask].copy()


def current_period(frame, date_column: str, window: ReportWindow):
    return filter_period(frame, date_column, window.start_time, window.end_time_exclusive)


def previous_period(frame, date_column: str, window: ReportWindow):
    return filter_period(frame, date_column, window.previous_start_time, window.previous_end_time)


def text_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if pd.isna(value):
        return default
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def clean_proactive_result(value: Any) -> str:
    result = text_value(value, "NotLinked").strip()
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


def proactive_result_label(value: Any) -> str:
    result = clean_proactive_result(value)
    return PROACTIVE_RESULT_LABELS.get(result, result)


def truncate_text(value: Any, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", text_value(value)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def normalize_title(value: Any) -> str:
    text = text_value(value).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"runner name:\s*\S+\s+region:\s*\S+\s+instance:\s*\S+\s+phase:\s*", "runner failure ", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", " ", text)
    text = re.sub(r"\b\d+\s+of\s+\d+\b", " ", text)
    text = re.sub(r"\b\d+(\.\d+)?%\b", " ", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b\d+\b", " ", text)
    text = re.sub(r"\b(eastus|eastus2|westus|westus2|westus3|centralus|northcentralus|southcentralus|westeurope|northeurope|germanywc|usgov|usdod|china)\w*\b", "<region>", text)
    text = re.sub(r"[^a-z0-9<>/ .:_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -:_")
    return text or "unknown issue"


def delta_label(current_count: int, previous_count: int) -> str:
    difference = current_count - previous_count
    sign = "+" if difference > 0 else ""
    if previous_count == 0:
        return f"{sign}{difference} vs prev"
    percent = difference / previous_count * 100
    return f"{sign}{difference} ({sign}{percent:.0f}%) vs prev"


def dataframe_for_metric(data: dict[str, Any], name: str):
    return data.get(name, pd.DataFrame())


def split_cri(frame):
    if frame.empty or "IncidentType" not in frame.columns:
        return frame.iloc[0:0].copy()
    return frame[frame["IncidentType"].astype(str).str.contains("CustomerReported|Customer Reported", case=False, na=False)].copy()


def split_non_runner_livesite(frame):
    if frame.empty or "IncidentType" not in frame.columns:
        return frame.iloc[0:0].copy()
    return frame[~frame["IncidentType"].astype(str).str.contains("Runner", case=False, na=False)].copy()


def build_summary_metrics(data: dict[str, Any], window: ReportWindow) -> list[dict[str, str]]:
    runner = dataframe_for_metric(data, "runner_sev2_detail")
    cri = split_cri(dataframe_for_metric(data, "cri_outage_detail"))
    livesite = split_non_runner_livesite(dataframe_for_metric(data, "livesite_detail"))
    acknowledge = dataframe_for_metric(data, "dri_acknowledge_detail")
    proactive = dataframe_for_metric(data, "proactive_linkage_detail")

    metric_specs = [
        ("Runner Sev2/25", runner, "LookingDate"),
        ("CRI", cri, "LookingDate"),
        ("LiveSite/Outage", livesite, "LookingDate"),
        ("DRI Acks", acknowledge, "AcknowledgeDate"),
    ]
    metrics: list[dict[str, str]] = []
    for label, frame, date_column in metric_specs:
        current_count = len(current_period(frame, date_column, window))
        previous_count = len(previous_period(frame, date_column, window))
        metrics.append({"label": label, "value": str(current_count), "delta": delta_label(current_count, previous_count)})

    proactive_current = current_period(proactive, "LinkedDate", window)
    total_children = len(proactive_current)
    succeeded = 0
    if total_children and "LinkResult" in proactive_current.columns:
        results = proactive_current["LinkResult"].map(clean_proactive_result)
        succeeded = int(results.isin(PROACTIVE_SUCCESS_RESULTS).sum())
    rate = 0 if total_children == 0 else round(succeeded / total_children * 100)
    metrics.append({"label": "Proactive Linkage", "value": f"{rate}%", "delta": f"{succeeded}/{total_children} succeeded"})
    return metrics


def rgb(color: tuple[int, int, int]):
    return RGBColor(color[0], color[1], color[2])


def set_run_font(run, size: int, color: tuple[int, int, int] = TEXT_COLOR, bold: bool = False) -> None:
    run.font.name = "Aptos"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)


def add_text(slide, text: str, left: float, top: float, width: float, height: float, size: int = 16, color: tuple[int, int, int] = TEXT_COLOR, bold: bool = False, align=None):
    shape = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    text_frame = shape.text_frame
    text_frame.clear()
    text_frame.margin_left = Inches(0.02)
    text_frame.margin_right = Inches(0.02)
    text_frame.margin_top = Inches(0.02)
    text_frame.margin_bottom = Inches(0.02)
    paragraph = text_frame.paragraphs[0]
    if align is not None:
        paragraph.alignment = align
    run = paragraph.add_run()
    run.text = text
    set_run_font(run, size, color, bold)
    return shape


def add_slide_title(slide, title: str, subtitle: str | None = None) -> None:
    add_text(slide, title, 0.45, 0.22, 12.3, 0.42, size=23, bold=True)
    if subtitle:
        add_text(slide, subtitle, 0.47, 0.66, 12.0, 0.28, size=9, color=MUTED_TEXT)


def add_footer(slide, window: ReportWindow) -> None:
    add_text(slide, f"Runner Review | {window.display_range}", 0.45, 7.16, 6.5, 0.2, size=7, color=MUTED_TEXT)


def add_metric_card(slide, label: str, value: str, delta: str, left: float, top: float, width: float, height: float, accent: tuple[int, int, int]) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(LIGHT_FILL)
    shape.line.color.rgb = rgb(GRID_COLOR)
    add_text(slide, label, left + 0.12, top + 0.12, width - 0.24, 0.25, size=9, color=MUTED_TEXT, bold=True)
    add_text(slide, value, left + 0.12, top + 0.43, width - 0.24, 0.45, size=25, color=accent, bold=True)
    add_text(slide, delta, left + 0.12, top + 0.94, width - 0.24, 0.25, size=8, color=MUTED_TEXT)


def style_table_cell(cell, size: int, bold: bool = False, fill: tuple[int, int, int] | None = None, color: tuple[int, int, int] = TEXT_COLOR) -> None:
    cell.margin_left = Inches(0.04)
    cell.margin_right = Inches(0.04)
    cell.margin_top = Inches(0.03)
    cell.margin_bottom = Inches(0.03)
    cell.vertical_anchor = MSO_ANCHOR.TOP
    if fill:
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb(fill)
    for paragraph in cell.text_frame.paragraphs:
        for run in paragraph.runs:
            set_run_font(run, size=size, color=color, bold=bold)


def add_table(slide, rows: list[dict[str, Any]], columns: list[tuple[str, str]], left: float, top: float, width: float, height: float, max_rows: int = 8, font_size: int = 7) -> None:
    visible_rows = rows[:max_rows]
    if not visible_rows:
        add_text(slide, "No data for this period", left, top + 0.1, width, 0.35, size=11, color=MUTED_TEXT)
        return
    table_shape = slide.shapes.add_table(len(visible_rows) + 1, len(columns), Inches(left), Inches(top), Inches(width), Inches(height))
    table = table_shape.table
    column_width = width / max(1, len(columns))
    for column_index, (_, header) in enumerate(columns):
        table.columns[column_index].width = Inches(column_width)
        cell = table.cell(0, column_index)
        cell.text = header
        style_table_cell(cell, size=font_size, bold=True, fill=HEADER_FILL, color=(255, 255, 255))
    for row_index, row in enumerate(visible_rows, start=1):
        for column_index, (key, _) in enumerate(columns):
            cell = table.cell(row_index, column_index)
            cell.text = truncate_text(row.get(key, ""), 110)
            fill = (250, 252, 253) if row_index % 2 == 0 else None
            style_table_cell(cell, size=font_size, fill=fill)


def save_placeholder_chart(path: Path, title: str) -> None:
    figure, axis = plt.subplots(figsize=(8, 3.4), dpi=160)
    axis.axis("off")
    axis.text(0.5, 0.55, "No data for this period", ha="center", va="center", fontsize=13, color="#5b6775")
    axis.set_title(title, loc="left", fontsize=12, color="#222831", pad=10)
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def save_line_chart(frame, date_column: str, path: Path, title: str, category_column: str | None = None, frequency: str = "15D") -> None:
    if frame.empty or date_column not in frame.columns:
        save_placeholder_chart(path, title)
        return
    work = frame.dropna(subset=[date_column]).copy()
    if work.empty:
        save_placeholder_chart(path, title)
        return
    figure, axis = plt.subplots(figsize=(8.6, 3.4), dpi=160)
    if category_column and category_column in work.columns:
        grouped = work.groupby([pd.Grouper(key=date_column, freq=frequency), category_column]).size().unstack(fill_value=0)
        grouped = grouped[grouped.sum().sort_values(ascending=False).head(6).index]
        grouped.plot(ax=axis, marker="o", linewidth=2, color=CHART_COLORS[: len(grouped.columns)])
        axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False, fontsize=8)
    else:
        grouped = work.groupby(pd.Grouper(key=date_column, freq=frequency)).size()
        axis.plot(grouped.index, grouped.values, marker="o", linewidth=2.5, color="#2969b0")
    axis.set_title(title, loc="left", fontsize=12, color="#222831", pad=10)
    axis.set_ylabel("Count")
    axis.grid(True, axis="y", color="#dfe4ea", linewidth=0.8)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    figure.autofmt_xdate(rotation=25)
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def save_bar_chart(series, path: Path, title: str, horizontal: bool = True) -> None:
    if series is None or len(series) == 0:
        save_placeholder_chart(path, title)
        return
    figure, axis = plt.subplots(figsize=(8.6, 3.6), dpi=160)
    plot_series = series.sort_values(ascending=True) if horizontal else series
    if horizontal:
        axis.barh(plot_series.index.astype(str), plot_series.values, color="#2969b0")
        axis.set_xlabel("Count")
    else:
        axis.bar(plot_series.index.astype(str), plot_series.values, color="#2969b0")
        axis.tick_params(axis="x", labelrotation=30)
    axis.set_title(title, loc="left", fontsize=12, color="#222831", pad=10)
    axis.grid(True, axis="x" if horizontal else "y", color="#dfe4ea", linewidth=0.8)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def add_picture(slide, image_path: Path, left: float, top: float, width: float, height: float) -> None:
    slide.shapes.add_picture(str(image_path), Inches(left), Inches(top), width=Inches(width), height=Inches(height))


def metric_rows_for_summary(metrics: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"Metric": item["label"], "Current": item["value"], "Previous comparison": item["delta"]} for item in metrics]


def add_summary_slide(presentation, data: dict[str, Any], window: ReportWindow) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_slide_title(slide, "Runner Review", f"Current: {window.display_range} | Previous: {window.previous_display_range}")
    metrics = build_summary_metrics(data, window)
    accents = [ACCENT_BLUE, ACCENT_GREEN, ACCENT_ORANGE, ACCENT_RED, ACCENT_TEAL]
    for index, metric in enumerate(metrics):
        add_metric_card(slide, metric["label"], metric["value"], metric["delta"], 0.45 + index * 2.52, 1.05, 2.28, 1.35, accents[index % len(accents)])
    add_text(slide, "Executive Readout", 0.55, 2.75, 3.2, 0.3, size=15, bold=True)
    add_table(slide, metric_rows_for_summary(metrics), [("Metric", "Metric"), ("Current", "Current"), ("Previous comparison", "Previous comparison")], 0.55, 3.13, 5.7, 2.65, max_rows=6, font_size=9)
    add_text(slide, "Generated from cached or live Kusto query results. Raw CSVs are kept in report/output/cache for audit and reruns.", 6.75, 3.22, 5.7, 0.9, size=12, color=MUTED_TEXT)
    add_footer(slide, window)


def add_cri_trend_slide(presentation, data: dict[str, Any], window: ReportWindow, asset_dir: Path) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_slide_title(slide, "CRI Trend", "180-day mitigated/resolved trend using LookingDate = ResolveDate, MitigateDate, CreateDate")
    cri = split_cri(dataframe_for_metric(data, "cri_outage_detail"))
    trend_frame = filter_period(cri, "LookingDate", window.trend_start_time, window.end_time_exclusive)
    chart_path = asset_dir / "cri_trend.png"
    save_line_chart(trend_frame, "LookingDate", chart_path, "CRI trend", frequency="15D")
    add_picture(slide, chart_path, 0.55, 1.05, 7.3, 4.45)
    current_cri = current_period(cri, "LookingDate", window)
    top_team_series = current_cri.groupby("OwningTeamName").size().sort_values(ascending=False).head(8) if not current_cri.empty and "OwningTeamName" in current_cri.columns else pd.Series(dtype=int)
    side_chart_path = asset_dir / "cri_top_teams.png"
    save_bar_chart(top_team_series, side_chart_path, "Current period by team")
    add_picture(slide, side_chart_path, 8.2, 1.08, 4.55, 3.3)
    top_rows = top_issue_rows(current_cri, dataset_name="CRI", max_rows=5)
    add_table(slide, top_rows, [("Team", "Team"), ("Count", "#"), ("Issue", "Top issue")], 8.2, 4.62, 4.55, 1.9, max_rows=5, font_size=7)
    add_footer(slide, window)


def add_livesite_slide(presentation, data: dict[str, Any], window: ReportWindow, asset_dir: Path) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_slide_title(slide, "LiveSites By Monitor", "Current period LiveSite/outage incidents grouped by monitor and team")
    livesite = split_non_runner_livesite(dataframe_for_metric(data, "livesite_detail"))
    current_livesite = current_period(livesite, "LookingDate", window)
    monitor_column = "MonitorName" if "MonitorName" in current_livesite.columns else "IncidentClass"
    monitor_series = current_livesite[monitor_column].replace("", "Other").fillna("Other").value_counts().head(12) if not current_livesite.empty and monitor_column in current_livesite.columns else pd.Series(dtype=int)
    chart_path = asset_dir / "livesite_by_monitor.png"
    save_bar_chart(monitor_series, chart_path, "Top monitors")
    add_picture(slide, chart_path, 0.55, 1.02, 6.3, 4.65)
    team_series = current_livesite.groupby("OwningTeamName").size().sort_values(ascending=False).head(10) if not current_livesite.empty and "OwningTeamName" in current_livesite.columns else pd.Series(dtype=int)
    team_chart_path = asset_dir / "livesite_by_team.png"
    save_bar_chart(team_series, team_chart_path, "Top teams")
    add_picture(slide, team_chart_path, 7.15, 1.02, 5.35, 3.1)
    rows = incident_detail_rows(current_livesite, max_rows=6)
    add_table(slide, rows, [("IncidentId", "ICM"), ("Team", "Team"), ("Severity", "Sev"), ("Title", "Title")], 7.15, 4.34, 5.35, 2.0, max_rows=6, font_size=6)
    add_footer(slide, window)


def add_acknowledge_slide(presentation, data: dict[str, Any], window: ReportWindow, asset_dir: Path) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_slide_title(slide, "DRI Acknowledge", "Daily acknowledge trend split by LiveSite, CRI, Runner, and proactive")
    acknowledge = dataframe_for_metric(data, "dri_acknowledge_detail")
    current_ack = current_period(acknowledge, "AcknowledgeDate", window)
    chart_path = asset_dir / "ack_trend.png"
    save_line_chart(current_ack, "AcknowledgeDate", chart_path, "Acknowledge trend", category_column="IcmType", frequency="1D")
    add_picture(slide, chart_path, 0.55, 1.02, 7.1, 4.3)
    spike_rows = acknowledge_spike_rows(current_ack, max_rows=7)
    add_text(slide, "Spiky Patterns", 8.0, 1.1, 4.0, 0.28, size=14, bold=True)
    add_table(slide, spike_rows, [("Date", "Date"), ("Team", "Ack team"), ("Type", "Type"), ("Count", "#")], 8.0, 1.48, 4.65, 2.25, max_rows=7, font_size=7)
    repeated_rows = repeated_issue_rows(current_ack, max_rows=6)
    add_text(slide, "Repeated Titles", 8.0, 4.05, 4.0, 0.28, size=14, bold=True)
    add_table(slide, repeated_rows, [("Count", "#"), ("Issue", "Normalized title")], 8.0, 4.42, 4.65, 1.86, max_rows=6, font_size=7)
    add_footer(slide, window)


def add_team_comparison_slide(presentation, data: dict[str, Any], window: ReportWindow) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_slide_title(slide, "Team Comparison", "Current period compared with the previous equal-length period")
    rows = team_comparison_rows(data, window, max_rows=12)
    add_table(slide, rows, [("Team", "Team"), ("Runner", "Runner"), ("CRI", "CRI"), ("LiveSite", "LiveSite"), ("Current", "Current"), ("Previous", "Previous"), ("Delta", "Delta")], 0.55, 1.08, 12.25, 5.55, max_rows=12, font_size=8)
    add_footer(slide, window)


def add_deep_dive_slide(presentation, data: dict[str, Any], window: ReportWindow) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_slide_title(slide, "NRP RNM NSM Deep Dive", "Detail ICMs matched by title, team, tenant, category, monitor, or runner metadata")
    rows = deep_dive_rows(data, window, max_rows=12)
    add_table(slide, rows, [("Area", "Area"), ("IncidentId", "ICM"), ("Team", "Team"), ("Severity", "Sev"), ("Status", "Status"), ("Title", "Title")], 0.55, 1.05, 12.25, 5.7, max_rows=12, font_size=7)
    add_footer(slide, window)


def add_top_issues_slide(presentation, data: dict[str, Any], window: ReportWindow) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_slide_title(slide, "Top Issues By Team", "Deterministic title/RCA grouping for current-period Runner, CRI, and LiveSite incidents")
    rows = combined_top_issue_rows(data, window, max_rows=14)
    add_table(slide, rows, [("Dataset", "Type"), ("Team", "Team"), ("Count", "#"), ("RCA", "RCA"), ("Issue", "Issue")], 0.55, 1.02, 12.25, 5.72, max_rows=14, font_size=6)
    add_footer(slide, window)


def add_proactive_slide(presentation, data: dict[str, Any], window: ReportWindow, asset_dir: Path) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_slide_title(slide, "Runner Proactive Linkage", "Current period linkage status for Runner Sev2/Sev2.5 child incidents")
    proactive = dataframe_for_metric(data, "proactive_linkage_detail")
    current_proactive = current_period(proactive, "LinkedDate", window)
    series = current_proactive["LinkResult"].map(proactive_result_label).value_counts() if not current_proactive.empty and "LinkResult" in current_proactive.columns else pd.Series(dtype=int)
    chart_path = asset_dir / "proactive_linkage.png"
    save_bar_chart(series, chart_path, "Linkage result")
    add_picture(slide, chart_path, 0.55, 1.02, 6.2, 4.2)
    rows = proactive_rows(current_proactive, max_rows=8)
    add_table(slide, rows, [("RunnerIncidentId", "Runner ICM"), ("LinkResult", "Result"), ("Team", "Team"), ("Title", "Title")], 7.0, 1.08, 5.65, 4.72, max_rows=8, font_size=6)
    add_footer(slide, window)


def add_oaas_slide(presentation, data: dict[str, Any], window: ReportWindow, asset_dir: Path) -> None:
    oaas = dataframe_for_metric(data, "oaas_human_touch")
    if oaas.empty:
        return
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    add_slide_title(slide, "OaaS vs Human Touch", "Optional NRP operation audit view")
    chart_path = asset_dir / "oaas_human_touch.png"
    save_line_chart(oaas, "PreciseTimeStamp", chart_path, "NRP operations by identity", category_column="UserIdentity", frequency="7D")
    add_picture(slide, chart_path, 0.75, 1.08, 11.7, 5.2)
    add_footer(slide, window)


def top_issue_rows(frame, dataset_name: str, max_rows: int) -> list[dict[str, Any]]:
    if frame.empty or "Title" not in frame.columns:
        return []
    work = frame.copy()
    work["Issue"] = work["Title"].map(normalize_title)
    team_column = "OwningTeamName" if "OwningTeamName" in work.columns else None
    group_columns = ["Issue"] + ([team_column] if team_column else [])
    grouped = work.groupby(group_columns, dropna=False).size().reset_index(name="Count").sort_values("Count", ascending=False).head(max_rows)
    rows = []
    for _, row in grouped.iterrows():
        rows.append({"Dataset": dataset_name, "Team": text_value(row.get(team_column), "Unknown"), "Count": str(int(row["Count"])), "Issue": truncate_text(row["Issue"], 90)})
    return rows


def incident_detail_rows(frame, max_rows: int) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    sort_column = "LookingDate" if "LookingDate" in frame.columns else "CreateDate"
    work = frame.sort_values(sort_column, ascending=False) if sort_column in frame.columns else frame
    rows = []
    for _, row in work.head(max_rows).iterrows():
        rows.append({
            "IncidentId": text_value(row.get("IncidentId")),
            "Team": text_value(row.get("OwningTeamName")),
            "Severity": text_value(row.get("Severity")),
            "Status": text_value(row.get("Status")),
            "Title": truncate_text(row.get("Title"), 100),
        })
    return rows


def acknowledge_spike_rows(frame, max_rows: int) -> list[dict[str, Any]]:
    if frame.empty or "AcknowledgeDate" not in frame.columns:
        return []
    work = frame.copy()
    work["Date"] = work["AcknowledgeDate"].dt.strftime("%Y-%m-%d")
    group_columns = ["Date", "AcknowledgeTeamName", "IcmType"]
    grouped = work.groupby(group_columns, dropna=False).size().reset_index(name="Count").sort_values("Count", ascending=False).head(max_rows)
    return [{"Date": row["Date"], "Team": text_value(row["AcknowledgeTeamName"], "Unknown"), "Type": text_value(row["IcmType"]), "Count": str(int(row["Count"]))} for _, row in grouped.iterrows()]


def repeated_issue_rows(frame, max_rows: int) -> list[dict[str, Any]]:
    if frame.empty or "Title" not in frame.columns:
        return []
    work = frame.copy()
    work["Issue"] = work["Title"].map(normalize_title)
    grouped = work.groupby("Issue").size().reset_index(name="Count").sort_values("Count", ascending=False)
    grouped = grouped[grouped["Count"] > 1].head(max_rows)
    return [{"Count": str(int(row["Count"])), "Issue": truncate_text(row["Issue"], 100)} for _, row in grouped.iterrows()]


def count_by_team(frame, date_column: str, window: ReportWindow, current: bool):
    period_frame = current_period(frame, date_column, window) if current else previous_period(frame, date_column, window)
    if period_frame.empty or "OwningTeamName" not in period_frame.columns:
        return pd.Series(dtype=int)
    return period_frame.groupby("OwningTeamName").size()


def team_comparison_rows(data: dict[str, Any], window: ReportWindow, max_rows: int) -> list[dict[str, Any]]:
    runner = dataframe_for_metric(data, "runner_sev2_detail")
    cri = split_cri(dataframe_for_metric(data, "cri_outage_detail"))
    livesite = split_non_runner_livesite(dataframe_for_metric(data, "livesite_detail"))
    current_runner = count_by_team(runner, "LookingDate", window, True)
    current_cri = count_by_team(cri, "LookingDate", window, True)
    current_livesite = count_by_team(livesite, "LookingDate", window, True)
    previous_runner = count_by_team(runner, "LookingDate", window, False)
    previous_cri = count_by_team(cri, "LookingDate", window, False)
    previous_livesite = count_by_team(livesite, "LookingDate", window, False)
    teams = sorted(set(current_runner.index) | set(current_cri.index) | set(current_livesite.index) | set(previous_runner.index) | set(previous_cri.index) | set(previous_livesite.index))
    rows = []
    for team in teams:
        runner_count = int(current_runner.get(team, 0))
        cri_count = int(current_cri.get(team, 0))
        livesite_count = int(current_livesite.get(team, 0))
        current_total = runner_count + cri_count + livesite_count
        previous_total = int(previous_runner.get(team, 0) + previous_cri.get(team, 0) + previous_livesite.get(team, 0))
        rows.append({
            "Team": text_value(team, "Unknown"),
            "Runner": str(runner_count),
            "CRI": str(cri_count),
            "LiveSite": str(livesite_count),
            "Current": str(current_total),
            "Previous": str(previous_total),
            "Delta": f"{current_total - previous_total:+d}",
            "Sort": current_total,
        })
    rows.sort(key=lambda item: item["Sort"], reverse=True)
    return rows[:max_rows]


def combine_current_incidents(data: dict[str, Any], window: ReportWindow):
    frames = []
    specs = [
        ("Runner", dataframe_for_metric(data, "runner_sev2_detail"), "LookingDate"),
        ("CRI", split_cri(dataframe_for_metric(data, "cri_outage_detail")), "LookingDate"),
        ("LiveSite", split_non_runner_livesite(dataframe_for_metric(data, "livesite_detail")), "LookingDate"),
    ]
    for dataset_name, frame, date_column in specs:
        current_frame = current_period(frame, date_column, window)
        if current_frame.empty:
            continue
        copy_frame = current_frame.copy()
        copy_frame["Dataset"] = dataset_name
        frames.append(copy_frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def detect_area(row) -> str:
    combined = " ".join(
        text_value(row.get(column))
        for column in ["Title", "OwningTeamName", "OwningTenantName", "Category", "MonitorName", "IncidentClass", "RunnerName", "ResponsibleTeamName"]
    ).upper()
    for area in ["NRP", "RNM", "NSM"]:
        if area in combined:
            return area
    return "Other"


def deep_dive_rows(data: dict[str, Any], window: ReportWindow, max_rows: int) -> list[dict[str, Any]]:
    combined = combine_current_incidents(data, window)
    if combined.empty:
        return []
    combined["Area"] = combined.apply(detect_area, axis=1)
    filtered = combined[combined["Area"].isin(["NRP", "RNM", "NSM"])].copy()
    if filtered.empty:
        return []
    sort_column = "LookingDate" if "LookingDate" in filtered.columns else "CreateDate"
    filtered = filtered.sort_values(sort_column, ascending=False) if sort_column in filtered.columns else filtered
    rows = []
    for _, row in filtered.head(max_rows).iterrows():
        rows.append({
            "Area": row["Area"],
            "IncidentId": text_value(row.get("IncidentId")),
            "Team": text_value(row.get("OwningTeamName")),
            "Severity": text_value(row.get("Severity")),
            "Status": text_value(row.get("Status")),
            "Title": truncate_text(row.get("Title"), 120),
        })
    return rows


def combined_top_issue_rows(data: dict[str, Any], window: ReportWindow, max_rows: int) -> list[dict[str, Any]]:
    combined = combine_current_incidents(data, window)
    if combined.empty or "Title" not in combined.columns:
        return []
    combined = combined.copy()
    combined["Issue"] = combined["Title"].map(normalize_title)
    if "RCATitle" not in combined.columns:
        combined["RCATitle"] = ""
    if "OwningTeamName" not in combined.columns:
        combined["OwningTeamName"] = "Unknown"
    grouped = (
        combined.groupby(["Dataset", "OwningTeamName", "Issue", "RCATitle"], dropna=False)
        .size()
        .reset_index(name="Count")
        .sort_values("Count", ascending=False)
        .head(max_rows)
    )
    rows = []
    for _, row in grouped.iterrows():
        rows.append({
            "Dataset": text_value(row["Dataset"]),
            "Team": text_value(row["OwningTeamName"], "Unknown"),
            "Count": str(int(row["Count"])),
            "RCA": truncate_text(row["RCATitle"], 70),
            "Issue": truncate_text(row["Issue"], 120),
        })
    return rows


def proactive_rows(frame, max_rows: int) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    sort_column = "LinkedDate" if "LinkedDate" in frame.columns else None
    work = frame.sort_values(sort_column, ascending=False) if sort_column else frame
    rows = []
    for _, row in work.head(max_rows).iterrows():
        rows.append({
            "RunnerIncidentId": text_value(row.get("RunnerIncidentId")),
            "LinkResult": proactive_result_label(row.get("LinkResult")),
            "Team": text_value(row.get("OwningTeamName")),
            "Title": truncate_text(row.get("RunnerTitle"), 110),
        })
    return rows


def build_presentation(data: dict[str, Any], config: dict[str, Any], window: ReportWindow, output_path: Path) -> None:
    initialize_ppt_modules()
    asset_dir = DEFAULT_ASSET_DIR
    asset_dir.mkdir(parents=True, exist_ok=True)
    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    add_summary_slide(presentation, data, window)
    add_cri_trend_slide(presentation, data, window, asset_dir)
    add_livesite_slide(presentation, data, window, asset_dir)
    add_acknowledge_slide(presentation, data, window, asset_dir)
    add_team_comparison_slide(presentation, data, window)
    add_deep_dive_slide(presentation, data, window)
    add_top_issues_slide(presentation, data, window)
    add_proactive_slide(presentation, data, window, asset_dir)
    add_oaas_slide(presentation, data, window, asset_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(output_path)


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    trend_days = args.trend_days or int(config.get("report", {}).get("default_trend_days", 180))
    window = build_window(args.start, args.end, trend_days)
    if args.out is None:
        args.out = SCRIPT_DIR / "output" / f"runner-review-{window.start_date.isoformat()}-{window.end_date.isoformat()}.pptx"
    query_configs = selected_queries(config, args.query)
    params = build_template_params(config, window)
    rendered_queries: dict[str, str] = {}
    for query_name, query_config in query_configs.items():
        template_path = (args.config.parent / query_config["template"]).resolve()
        rendered_query = render_template(template_path, params)
        rendered_queries[query_name] = rendered_query
        if args.render_kql:
            args.render_kql.mkdir(parents=True, exist_ok=True)
            (args.render_kql / f"{query_name}.kql").write_text(rendered_query, encoding="utf-8")
    if args.render_only:
        print(f"Rendered {len(rendered_queries)} KQL template(s).")
        return 0

    initialize_data_modules()
    raw_data = {}
    for query_name, query_config in query_configs.items():
        raw_data[query_name] = load_or_query_dataset(query_name, query_config, rendered_queries[query_name], args, window, trend_days)
    prepared_data = prepare_frames(raw_data)
    build_presentation(prepared_data, config, window, args.out)
    print(f"[pptx] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
