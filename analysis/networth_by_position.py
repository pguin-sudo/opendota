from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean, median

from matchdb.dataset import MatchData

from ._base import BaseAnalysis, Options, Plot, Report, ranked_matches, valid_player
from ._ranks import MEDALS, rank_group, rank_name
from ._statistics import DISTRIBUTION_NOTE, distribution, distribution_columns


@dataclass(slots=True)
class PositionSamples:
    matches: set[int] = field(default_factory=set)
    values: list[int] = field(default_factory=list)


class Analysis(BaseAnalysis):
    requires_players = True

    @staticmethod
    def positions(match: MatchData, source: str) -> tuple[tuple[int, int], ...]:
        result = []
        for offset in (0, 128):
            team = [p for p in match.players if offset <= p.player_slot < offset + 5]
            if len(team) != 5 or len({p.player_slot for p in team}) != 5:
                continue
            if any(
                not valid_player(p) or p.net_worth is None or p.net_worth < 0
                for p in team
            ):
                continue
            if source == "networth":
                team.sort(key=lambda p: (-int(p.net_worth or 0), p.player_slot))
                result.extend(
                    (position, int(player.net_worth or 0))
                    for position, player in enumerate(team, 1)
                )
            else:
                if {p.position for p in team} != {1, 2, 3, 4, 5}:
                    continue
                result.extend(
                    (int(p.position or 0), int(p.net_worth or 0)) for p in team
                )
        return tuple(result)

    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        groups: defaultdict[tuple[int, int], PositionSamples] = defaultdict(
            PositionSamples
        )
        for match in ranked_matches(matches):
            rank = rank_group(match.avg_rank_tier, detailed=options.detailed_ranks)
            if rank is None:
                continue
            for position, net_worth in self.positions(match, options.position_source):
                sample = groups[rank, position]
                sample.matches.add(match.match_id)
                sample.values.append(net_worth)
        rows = tuple(
            (
                rank,
                rank_name(rank),
                position,
                options.position_source,
                len(sample.matches),
                len(sample.values),
                mean(sample.values),
                median(sample.values),
                *distribution([float(value) for value in sample.values]),
            )
            for (rank, position), sample in sorted(groups.items())
            if len(sample.matches) >= options.min_matches
        )
        description = (
            "Позиция — явное поле position (1–5) в данных игрока. Команды без пяти разных позиций исключены. "
            "Без разметки используйте --position-source networth."
            if options.position_source == "explicit"
            else "Позиция — место по итоговому net worth внутри команды, а не игровая роль. "
            "1 — самый богатый игрок; при равенстве используется player_slot."
        )
        return Report(
            (
                "avg_rank_tier",
                "rank_name",
                "position",
                "position_source",
                "matches",
                "players",
                "mean_net_worth",
                "median_net_worth",
                *distribution_columns("net_worth"),
            ),
            rows,
            Plot(
                "avg_rank_tier",
                distribution_columns("net_worth"),
                "Распределение net worth по позиции и рангу",
                "Средний ранг матча (не MMR)",
                "Итоговый net worth",
                kind="distribution",
                labels="rank_name",
                categories=() if options.detailed_ranks else MEDALS,
                series="position",
                counts="players",
                counts_label="Наблюдений игроков",
            ),
            notes=(
                description,
                DISTRIBUTION_NOTE,
                "Учитываются только полные команды с известным неотрицательным net worth всех пяти игроков.",
            ),
        )
