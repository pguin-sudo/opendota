from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from math import nan
from pathlib import Path
from typing import cast

from analysis._base import Cell, Report


def sample_description(report: Report, rows: Sequence[tuple[Cell, ...]]) -> str:
    counts = []
    for column, label in (
        ("matches", "матчей"),
        ("players", "наблюдений игроков"),
        ("observations", "наблюдений"),
    ):
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
    positions = {
        value: index
        for index, value in enumerate(
            [value for value, _ in spec.categories] if spec.categories else unique_rows
        )
    }
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
    if report.normalization is not None:
        sample_labels.append(report.normalization)
    if spec.kind == "distribution":
        sample_labels.append(
            "Линия: медиана; тёмная область: P25–P75 (50%); светлая: P5–P95 (90%)."
        )
    generated_at = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S %z")
    figure.supxlabel(
        "\n".join([*sample_labels, f"Сформировано: {generated_at}"]), fontsize=9
    )
    count_index = report.columns.index(spec.counts) if spec.counts else None
    numeric_x = sorted(
        float(positions[value]) if spec.labels else float(cast(float, value))
        for value in unique_rows
    )
    spacing = (
        1 if spec.labels else min((b - a for a, b in pairwise(numeric_x)), default=1)
    )
    count_width = (spec.width if spec.kind == "bar" else 0.8 * spacing) / len(groups)
    has_negative = False
    for group_index, (key, rows) in enumerate(groups.items()):
        x = [
            positions[row[x_index]] if spec.labels else cast(float, row[x_index])
            for row in rows
        ]
        color = None
        if spec.kind == "distribution":
            for start in range(0, len(spec.y), 5):
                columns = list(spec.y[start : start + 5])
                quantiles = [
                    [
                        float(cast(float, row[report.columns.index(column)]))
                        for row in rows
                    ]
                    for column in columns
                ]
                label = columns[2].removeprefix("normalized_").removesuffix("_p50")
                if spec.series:
                    label = f"{spec.series}: {key}, {label}"
                line = axes.plot(
                    x, quantiles[2], marker="o", markersize=3, label=label
                )[0]
                shade = line.get_color()
                axes.fill_between(
                    x, quantiles[0], quantiles[4], color=shade, alpha=0.10
                )
                axes.fill_between(
                    x, quantiles[1], quantiles[3], color=shade, alpha=0.25
                )
                axes.vlines(x, quantiles[0], quantiles[4], color=shade, alpha=0.25)
                axes.vlines(
                    x, quantiles[1], quantiles[3], color=shade, alpha=0.5, linewidth=4
                )
                color = color or shade
                has_negative |= any(value < 0 for value in quantiles[0])
        for column in spec.y:
            if spec.kind == "distribution":
                break
            index = report.columns.index(column)
            values = [
                float(cast(float, row[index])) if row[index] is not None else nan
                for row in rows
            ]
            has_negative |= any(value < 0 for value in values)
            label = column
            if report.normalization is not None:
                label = label.removeprefix("normalized_")
            if spec.series:
                label = (
                    f"{spec.series}: {key}, {label}"
                    if len(spec.y) > 1
                    else f"{spec.series}: {key}"
                )
            if spec.kind == "bar":
                bars = axes.bar(x, values, width=spec.width, align="edge", label=label)
                if color is None:
                    color = bars.patches[0].get_facecolor()
            else:
                lines = axes.plot(x, values, marker="o", markersize=3, label=label)
                if color is None:
                    color = lines[0].get_color()
        if counts is not None and count_index is not None:
            offset = (group_index - (len(groups) - 1) / 2) * count_width
            bars = counts.bar(
                [value + offset for value in x],
                [cast(float, row[count_index]) for row in rows],
                width=count_width,
                align="edge" if spec.kind == "bar" else "center",
                color=color,
            )
            if len(report.rows) <= 40:
                counts.bar_label(bars, fmt="%.0f", fontsize=7, padding=2)
    axes.set_title(spec.title)
    axes.set_ylabel(spec.ylabel)
    if not has_negative:
        axes.set_ylim(bottom=0)
    axes.grid(axis="y", alpha=0.25)
    axes.set_axisbelow(True)
    if len(spec.y) > 1 or spec.series:
        axes.legend()
    bottom = axes
    if counts is not None and spec.counts is not None:
        counts.set_ylabel(spec.counts_label)
        counts.set_ylim(bottom=0)
        counts.margins(y=0.2)
        counts.grid(axis="y", alpha=0.25)
        counts.set_axisbelow(True)
        counts.yaxis.set_major_locator(MaxNLocator(integer=True))
        axes.tick_params(axis="x", labelbottom=False)
        bottom = counts
    bottom.set_xlabel(spec.xlabel)
    if spec.integer_x and not spec.labels:
        bottom.xaxis.set_major_locator(MaxNLocator(integer=True))
    if spec.labels:
        label_index = report.columns.index(spec.labels)
        categories = list(spec.categories) or [
            (row[x_index], f"{row[label_index]} ({row[x_index]})")
            for row in unique_rows.values()
        ]
        ticks = list(range(len(categories)))[:: max(1, (len(categories) + 11) // 12)]
        if len(categories) - 1 not in ticks:
            ticks.append(len(categories) - 1)
        bottom.set_xticks(
            ticks,
            [categories[i][1] for i in ticks],
            rotation=35,
            ha="right",
        )
        if spec.categories:
            bottom.set_xlim(-0.5, len(spec.categories) - 0.5)
    output.parent.mkdir(parents=True, exist_ok=True)
    FigureCanvasAgg(figure)
    figure.savefig(output, format=image_format, dpi=160, bbox_inches="tight")
