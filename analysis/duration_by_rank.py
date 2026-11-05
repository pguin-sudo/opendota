from collections import defaultdict
from statistics import mean, median

from matchdb.dataset import MatchData

from ._base import BaseAnalysis, Options, Plot, Report, ranked_matches
from ._models import RankDuration
from ._ranks import MEDALS, rank_group
from ._statistics import DISTRIBUTION_NOTE, distribution, distribution_columns

TITLE = "Длительность рейтинговых матчей по рангу"


class Analysis(BaseAnalysis):
    @staticmethod
    def calculate(
        matches: tuple[MatchData, ...], *, detailed_ranks: bool = False
    ) -> list[RankDuration]:
        groups: defaultdict[int, list[int]] = defaultdict(list)
        for match in ranked_matches(matches):
            rank = rank_group(match.avg_rank_tier, detailed=detailed_ranks)
            if rank is not None and match.duration is not None:
                groups[rank].append(match.duration)
        return [
            RankDuration(rank, len(values), mean(values), median(values))
            for rank, values in sorted(groups.items())
        ]

    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        rows = [
            row
            for row in self.calculate(matches, detailed_ranks=options.detailed_ranks)
            if row.matches >= options.min_matches
        ]
        samples: defaultdict[int, list[float]] = defaultdict(list)
        for match in ranked_matches(matches):
            rank = rank_group(match.avg_rank_tier, detailed=options.detailed_ranks)
            if rank is not None and match.duration is not None:
                samples[rank].append(match.duration / 60)
        return Report(
            (
                "avg_rank_tier",
                "rank_name",
                "matches",
                "mean_seconds",
                "median_seconds",
                "mean_minutes",
                "median_minutes",
                *distribution_columns("minutes"),
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
                    *distribution(samples[r.avg_rank_tier]),
                )
                for r in rows
            ),
            Plot(
                "avg_rank_tier",
                distribution_columns("minutes"),
                TITLE,
                "Средний ранг матча (не MMR)",
                "Длительность матча, мин",
                kind="distribution",
                labels="rank_name",
                categories=() if options.detailed_ranks else MEDALS,
                counts="matches",
            ),
            notes=(DISTRIBUTION_NOTE,),
        )
