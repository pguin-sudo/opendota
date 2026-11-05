from collections import Counter, defaultdict
from dataclasses import dataclass, field

from matchdb.dataset import MatchData

from ._base import BaseAnalysis, Options, Plot, Report, ranked_matches, valid_player
from ._history import identified_players, player_histories, recent_games


@dataclass(slots=True)
class Samples:
    matches: set[int] = field(default_factory=set)
    observations: int = 0
    events: int = 0


class Analysis(BaseAnalysis):
    requires_players = True

    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        groups: defaultdict[tuple[str, int], Samples] = defaultdict(Samples)
        eligible = sorted(
            (
                m
                for m in ranked_matches(matches)
                if m.start_time is not None and m.start_time > 0
            ),
            key=lambda m: (m.start_time, m.match_id),
        )
        history = player_histories(matches)
        max_history = 0
        eligible_players = 0
        for match in eligible:
            assert match.start_time is not None and match.duration is not None
            players = tuple(p for p in match.players if valid_player(p))
            complete = (
                len(players) == 10
                and len({p.player_slot for p in players}) == 10
                and len({p.hero_id for p in players}) == 10
            )
            for player in identified_players(match):
                assert player.account_id is not None
                recent = recent_games(
                    history[player.account_id],
                    match,
                    options.history_days,
                    options.history_matches,
                )
                max_history = max(max_history, len(recent))
                if len(recent) >= options.min_history:
                    eligible_players += 1
                    games = Counter(entry.hero_id for entry in recent)
                    wins = Counter(entry.hero_id for entry in recent if entry.won)
                    for hero, count in games.items():
                        outcomes = []
                        if match.banned_heroes is not None:
                            outcomes.append(("ban", hero in match.banned_heroes))
                        if complete:
                            outcomes.append(
                                (
                                    "enemy_pick",
                                    any(
                                        p.hero_id == hero
                                        and (p.player_slot < 128)
                                        != (player.player_slot < 128)
                                        for p in players
                                    ),
                                )
                            )
                        for metric, value in (("games", count), ("wins", wins[hero])):
                            for outcome, happened in outcomes:
                                group = groups[(f"{metric}:{outcome}", value)]
                                group.matches.add(match.match_id)
                                group.observations += 1
                                group.events += happened
        rows = tuple(
            (
                series,
                count,
                len(group.matches),
                group.observations,
                group.events,
                100 * group.events / group.observations,
            )
            for (series, count), group in sorted(groups.items())
            if len(group.matches) >= options.min_matches
        )
        return Report(
            ("series", "recent_count", "matches", "observations", "events", "percent"),
            rows,
            Plot(
                "recent_count",
                ("percent",),
                "Баны и пики соперника в зависимости от недавней истории",
                "Число игр / побед на герое в предыдущих матчах",
                "Доля наблюдений, %",
                integer_x=True,
                series="series",
                counts="observations",
                counts_label="Наблюдений",
            ),
            notes=(
                f"Игроков-матчей с достаточной историей: {eligible_players}; "
                f"максимум матчей истории в заданном окне: {max_history}.",
                f"История: до {options.history_matches} завершённых рейтинговых матчей "
                f"за {options.history_days} дней; минимум {options.min_history}. "
                "Учитываются только матчи, закончившиеся до начала текущего. "
                f"Для загрузки истории: python -m matchdb history --days {options.history_days} --limit 10.",
                "Наблюдение — игрок/герой/матч; герои берутся из недавней истории игрока. "
                "games — число игр, wins — число побед, ban — бан любой стороной, "
                "enemy_pick — герой в итоговом составе соперника. "
                "Неизвестные баны и неполные составы исключаются из соответствующего исхода.",
                "Это описательная связь, а не доказательство целенаправленного бана. "
                "История локальной базы может быть неполной; анонимные аккаунты исключены. "
                "Герои с нулём игр не сравниваются; ноль побед возможен. "
                "Популярность героя, патч, ранг и режим не контролируются. "
                "Наблюдения зависимы: один матч может учитываться несколько раз.",
            ),
        )
