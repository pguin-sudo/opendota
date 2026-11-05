from collections import Counter

from matchdb.dataset import MatchData

from ._base import BaseAnalysis, Options, Plot, Report, ranked_matches
from ._models import DurationBin

TITLE = "Распределение длительности рейтинговых матчей"


class Analysis(BaseAnalysis):
    @staticmethod
    def calculate(
        matches: tuple[MatchData, ...], bin_seconds: int = 60
    ) -> list[DurationBin]:
        if bin_seconds <= 0:
            raise ValueError("Размер интервала должен быть положительным")
        counts = Counter(
            (match.duration // bin_seconds) * bin_seconds
            for match in ranked_matches(matches)
            if match.duration is not None
        )
        total = sum(counts.values())
        cumulative = 0
        result = []
        for start, count in sorted(counts.items()):
            cumulative += count
            result.append(
                DurationBin(
                    start,
                    start + bin_seconds,
                    count,
                    round(count / total * 100, 6),
                    round(cumulative / total * 100, 6),
                )
            )
        return result

    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        rows = self.calculate(matches, options.bin_seconds)
        return Report(
            (
                "from_seconds",
                "to_seconds",
                "from_minutes",
                "to_minutes",
                "matches",
                "percent",
                "cumulative_percent",
            ),
            tuple(
                (
                    r.from_seconds,
                    r.to_seconds,
                    r.from_minutes,
                    r.to_minutes,
                    r.matches,
                    r.percent,
                    r.cumulative_percent,
                )
                for r in rows
            ),
            Plot(
                "from_minutes",
                ("matches",),
                TITLE,
                "Длительность матча, мин",
                "Количество матчей",
                kind="bar",
                width=options.bin_seconds / 60,
            ),
        )
