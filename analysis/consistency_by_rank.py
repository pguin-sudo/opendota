from collections import defaultdict
from dataclasses import dataclass, field

from matchdb.dataset import MatchData

from ._base import BaseAnalysis, Options, Plot, Report, ranked_matches, valid_player
from ._ranks import MEDALS, rank_group, rank_name
from ._statistics import Summary


@dataclass(slots=True)
class RankSamples:
    kda_matches: int = 0
    net_worth_matches: int = 0
    kda: list[float] = field(default_factory=list)
    net_worth: list[float] = field(default_factory=list)


class Analysis(BaseAnalysis):
    requires_players = True

    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        groups: defaultdict[int, RankSamples] = defaultdict(RankSamples)
        for match in ranked_matches(matches):
            rank = rank_group(match.avg_rank_tier, detailed=options.detailed_ranks)
            if rank is None:
                continue
            samples = RankSamples()
            for player in match.players:
                if not valid_player(player):
                    continue
                if (
                    player.kills is not None
                    and player.deaths is not None
                    and player.assists is not None
                    and min(player.kills, player.deaths, player.assists) >= 0
                ):
                    samples.kda.append(
                        (player.kills + player.assists) / max(1, player.deaths)
                    )
                if player.net_worth is not None and player.net_worth >= 0:
                    samples.net_worth.append(float(player.net_worth))
            if samples.kda or samples.net_worth:
                group = groups[rank]
                group.kda_matches += bool(samples.kda)
                group.net_worth_matches += bool(samples.net_worth)
                group.kda.extend(samples.kda)
                group.net_worth.extend(samples.net_worth)
        rows = []
        for rank, group in sorted(groups.items()):
            for metric, values, match_count in (
                ("kda", group.kda, group.kda_matches),
                ("net_worth", group.net_worth, group.net_worth_matches),
            ):
                if not values or match_count < options.min_matches:
                    continue
                summary = Summary.from_values(values)
                rows.append(
                    (
                        rank,
                        rank_name(rank),
                        metric,
                        match_count,
                        summary.samples,
                        summary.mean,
                        summary.median,
                        summary.stddev,
                        summary.cv,
                    )
                )
        return Report(
            (
                "avg_rank_tier",
                "rank_name",
                "metric",
                "matches",
                "players",
                "mean",
                "median",
                "stddev",
                "cv",
            ),
            tuple(rows),
            Plot(
                "avg_rank_tier",
                ("cv",),
                "Разброс KDA и net worth по рангам",
                "Средний ранг матча (не MMR)",
                "Коэффициент вариации",
                labels="rank_name",
                categories=() if options.detailed_ranks else MEDALS,
                series="metric",
                counts="players",
                counts_label="Наблюдений игроков",
            ),
            notes=(
                "KDA = (kills + assists) / max(1, deaths). CV = выборочное stddev / mean. "
                "Меньше CV — меньше относительный разброс. Это разброс игроков, а не стабильность одного игрока.",
            ),
        )
