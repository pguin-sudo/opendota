from collections import defaultdict
from dataclasses import dataclass, field

from matchdb.dataset import MatchData

from ._base import BaseAnalysis, Options, Plot, Report, ranked_matches
from ._history import identified_players, player_histories, recent_games


@dataclass(slots=True)
class Samples:
    matches: set[int] = field(default_factory=set)
    players: int = 0
    wins: int = 0


class Analysis(BaseAnalysis):
    requires_players = True
    streak_won: bool = True

    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        column = "previous_wins" if self.streak_won else "previous_losses"
        outcome = "побед" if self.streak_won else "поражений"
        history = player_histories(matches)
        groups: defaultdict[int, Samples] = defaultdict(Samples)
        insufficient = 0
        censored = 0
        for match in ranked_matches(matches):
            if match.start_time is None or match.start_time <= 0:
                continue
            for player in identified_players(match):
                assert player.account_id is not None
                recent = recent_games(
                    history[player.account_id],
                    match,
                    options.history_days,
                    options.history_matches,
                )
                if len(recent) < options.min_history:
                    insufficient += 1
                    continue
                streak = 0
                for game in reversed(recent):
                    if game.won != self.streak_won:
                        break
                    streak += 1
                else:
                    censored += 1
                    continue
                group = groups[streak]
                group.matches.add(match.match_id)
                group.players += 1
                group.wins += match.radiant_win == (player.player_slot < 128)
        rows = tuple(
            (
                streak,
                len(group.matches),
                group.players,
                group.wins,
                100 * group.wins / group.players,
            )
            for streak, group in sorted(groups.items())
            if len(group.matches) >= options.min_matches
        )
        return Report(
            (column, "matches", "players", "wins", "win_percent"),
            rows,
            Plot(
                column,
                ("win_percent",),
                f"Вероятность победы после серии {outcome}",
                f"Серия {outcome} перед матчем",
                "Доля побед, %",
                integer_x=True,
                counts="players",
                counts_label="Наблюдений игроков",
            ),
            notes=(
                f"История: до {options.history_matches} завершённых рейтинговых игр "
                f"за {options.history_days} дней; минимум {options.min_history}. "
                "Текущая игра и матчи, не завершённые до её начала, исключены из истории.",
                f"Серия {outcome} считается с последней игры назад до противоположного исхода. "
                "0 — последняя игра имеет противоположный исход. Серии без противоположного исхода "
                "до границы доступной истории, исключены: их точная длина неизвестна. "
                f"Исключено из-за короткой истории: {insufficient}; "
                f"из-за неизвестного начала серии: {censored}.",
                "Наблюдение — игрок в текущем матче. wins / players * 100 — доля побед. "
                "matches — уникальные матчи; --min-matches применяется к каждой длине серии. "
                "Анонимные аккаунты исключены. История локальной базы может быть неполной; "
                "серии определяются по доступным рейтинговым играм. "
                "Наблюдения игроков одного матча зависимы; причинный эффект не оценивается.",
                f"Для загрузки истории: python -m matchdb history --days {options.history_days} --limit 100.",
            ),
        )
