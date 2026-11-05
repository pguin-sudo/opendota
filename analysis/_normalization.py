from collections import defaultdict
from dataclasses import replace
from math import isfinite
from typing import cast

from ._base import Cell, Report

NORMALIZATION = (
    "Нормализация: точка и ближайшие соседи слева/справа; "
    "вес — доля выборки в этом окне."
)


def normalize_report(report: Report) -> Report:
    spec = report.plot
    if (
        report.normalization is not None
        or spec is None
        or spec.counts is None
        or not report.rows
    ):
        return report
    x_index = report.columns.index(spec.x)
    count_index = report.columns.index(spec.counts)
    series_index = report.columns.index(spec.series) if spec.series else None
    y_indices = [report.columns.index(column) for column in spec.y]
    columns = tuple(f"normalized_{column}" for column in spec.y)
    if set(columns) & set(report.columns):
        raise ValueError("Столбцы нормализации уже присутствуют в отчёте")
    groups: defaultdict[Cell, list[int]] = defaultdict(list)
    for index, row in enumerate(report.rows):
        groups[row[series_index] if series_index is not None else None].append(index)
    rows = list(report.rows)
    for indices in groups.values():
        indices.sort(key=lambda index: cast(float, report.rows[index][x_index]))
        for position, index in enumerate(indices):
            neighbors = indices[max(0, position - 1) : position + 2]
            normalized: list[Cell] = []
            for y_index in y_indices:
                current = report.rows[index][y_index]
                if current is None or not isfinite(cast(float, current)):
                    normalized.append(None)
                    continue
                weighted = 0.0
                total = 0.0
                for neighbor in neighbors:
                    value = report.rows[neighbor][y_index]
                    weight = cast(float, report.rows[neighbor][count_index])
                    if (
                        value is not None
                        and isfinite(cast(float, value))
                        and isfinite(weight)
                        and weight > 0
                    ):
                        weighted += cast(float, value) * weight
                        total += weight
                normalized.append(weighted / total if total else None)
            rows[index] += tuple(normalized)
    return replace(
        report,
        columns=report.columns + columns,
        rows=tuple(rows),
        plot=replace(spec, y=columns),
        notes=(*report.notes, NORMALIZATION),
        normalization=NORMALIZATION,
    )
