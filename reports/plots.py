from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from math import nan
from pathlib import Path
from typing import cast

from analysis._base import Cell, Report


def sample_description(report: Report, rows: Sequence[tuple[Cell, ...]]) -> str:
    counts = []
    for column, label in (("matches", "матчей"), ("players", "наблюдений игроков")):
        if column in report.columns:
            index = report.columns.index(column)
            count = sum(cast(int, row[index]) for row in rows)
            counts.append(f"{label}: {count:,}".replace(",", " "))
    return "; ".join(counts) if counts else f"строк результата: {len(rows)}"


def plot_report(report: Report, output: Path) -> None:
    if not report.rows:
        raise ValueError("Нет данных для построения графика")
    spec = report.plot
    if spec is None:
        raise ValueError("Этот анализ не задаёт график")
    image_format = output.suffix.lower().removeprefix(".")
    if image_format not in {"png", "svg", "pdf"}:
        raise ValueError("Укажите расширение .png, .svg или .pdf")
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import MaxNLocator

    figure = Figure(figsize=(11, 7), layout="constrained")
    if spec.counts:
        grid = figure.add_gridspec(2, 1, height_ratios=[3, 1])
        axes = figure.add_subplot(grid[0])
        counts = figure.add_subplot(grid[1], sharex=axes)
    else:
        axes = figure.add_subplot()
        counts = None
    x_index = report.columns.index(spec.x)
    unique_rows = {row[x_index]: row for row in report.rows}
    positions = {value: index for index, value in enumerate(unique_rows)}
    groups: defaultdict[Cell, list[tuple[Cell, ...]]] = defaultdict(list)
    for row in report.rows:
        key = row[report.columns.index(spec.series)] if spec.series else None
        groups[key].append(row)
    sample_labels = [
        f"Выборка ({spec.series}: {key}): {sample_description(report, rows)}"
        if spec.series
        else f"Выборка: {sample_description(report, rows)}"
        for key, rows in groups.items()
    ]
    generated_at = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S %z")
    figure.supxlabel(
        "\n".join([*sample_labels, f"Сформировано: {generated_at}"]), fontsize=9
    )
    for key, rows in groups.items():
        x = [
            positions[row[x_index]] if spec.labels else cast(float, row[x_index])
            for row in rows
        ]
        for column in spec.y:
            index = report.columns.index(column)
            values = [
                float(cast(float, row[index])) if row[index] is not None else nan
                for row in rows
            ]
            label = f"{spec.series}: {key}" if spec.series else column
            if spec.kind == "bar":
                axes.bar(x, values, width=spec.width, align="edge", label=label)
            else:
                axes.plot(x, values, marker="o", markersize=3, label=label)
    axes.set_title(spec.title)
    axes.set_ylabel(spec.ylabel)
    axes.set_ylim(bottom=0)
    axes.grid(axis="y", alpha=0.25)
    axes.set_axisbelow(True)
    if len(spec.y) > 1 or spec.series:
        axes.legend()
    bottom = axes
    if counts is not None and spec.counts is not None:
        count_index = report.columns.index(spec.counts)
        counts.bar(
            list(positions.values()),
            [cast(float, row[count_index]) for row in unique_rows.values()],
        )
        counts.set_ylabel("Матчей")
        counts.yaxis.set_major_locator(MaxNLocator(integer=True))
        axes.tick_params(axis="x", labelbottom=False)
        bottom = counts
    bottom.set_xlabel(spec.xlabel)
    if spec.labels:
        label_index = report.columns.index(spec.labels)
        categories = list(unique_rows.values())
        ticks = list(range(len(categories)))[:: max(1, (len(categories) + 11) // 12)]
        if len(categories) - 1 not in ticks:
            ticks.append(len(categories) - 1)
        bottom.set_xticks(
            ticks,
            [f"{categories[i][label_index]} ({categories[i][x_index]})" for i in ticks],
            rotation=35,
            ha="right",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    FigureCanvasAgg(figure)
    figure.savefig(output, format=image_format, dpi=160, bbox_inches="tight")
