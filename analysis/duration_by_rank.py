from collections import defaultdict
from statistics import mean, median

from matchdb.dataset import MatchData

from ._base import BaseAnalysis, Options, Plot, Report, ranked_matches
from ._models import RankDuration

TITLE = "Длительность рейтинговых матчей по рангу"


class Analysis(BaseAnalysis):
    @staticmethod
    def calculate(matches: tuple[MatchData, ...]) -> list[RankDuration]:
        groups: defaultdict[int, list[int]] = defaultdict(list)
        for match in ranked_matches(matches):
            if (
                match.avg_rank_tier is not None
                and match.avg_rank_tier > 0
                and match.duration is not None
            ):
                groups[match.avg_rank_tier].append(match.duration)
        return [
            RankDuration(rank, len(values), mean(values), median(values))
            for rank, values in sorted(groups.items())
        ]

    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        rows = [
            row for row in self.calculate(matches) if row.matches >= options.min_matches
        ]
        return Report(
            (
                "avg_rank_tier",
                "rank_name",
                "matches",
                "mean_seconds",
                "median_seconds",
                "mean_minutes",
                "median_minutes",
            ),
            tuple(
                (
                    r.avg_rank_tier,
                    r.rank_name,
                    r.matches,
                    r.mean_seconds,
                    r.median_seconds,
                    r.mean_minutes,
                    r.median_minutes,
                )
                for r in rows
            ),
            Plot(
                "avg_rank_tier",
                ("mean_minutes", "median_minutes"),
                TITLE,
                "Средний ранг матча (не MMR)",
                "Длительность матча, мин",
                labels="rank_name",
                counts="matches",
            ),
        )
