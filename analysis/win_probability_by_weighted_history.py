from collections import defaultdict
from dataclasses import dataclass, field

from matchdb.dataset import MatchData

from ._base import BaseAnalysis, Options, Plot, Report, ranked_matches
from ._history import identified_players, player_histories
from ._weighted_history import estimate_weight, score_interval, weight_bin


@dataclass(slots=True)
class Samples:
    matches: set[int] = field(default_factory=set)
    players: int = 0
    wins: int = 0
    complete_players: int = 0
    bounded_players: int = 0
    unverified_players: int = 0
    max_tail_error: float = 0.0


class Analysis(BaseAnalysis):
    requires_players = True

    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        history = player_histories(matches)
        incomplete = 0
        groups: defaultdict[int, Samples] = defaultdict(Samples)
        insufficient = 0
        max_history = 0
        for match in ranked_matches(matches):
            if match.start_time is None or match.start_time <= 0:
                continue
            for player in identified_players(match):
                assert player.account_id is not None
                weight = estimate_weight(
                    player, match, history[player.account_id], options
                )
                if weight is None:
                    insufficient += 1
                    continue
                index = weight_bin(weight, options.form_bins)
                if index is None:
                    incomplete += 1
                    continue
                max_history = max(max_history, weight.games)
                group = groups[index]
                group.matches.add(match.match_id)
                group.players += 1
                group.complete_players += weight.complete
                group.bounded_players += (
                    weight.tail_error is not None and not weight.complete
                )
                group.unverified_players += weight.tail_error is None
                group.max_tail_error = max(group.max_tail_error, weight.tail_error or 0)
                group.wins += match.radiant_win == (player.player_slot < 128)
        rows = tuple(
            (
                *score_interval(index, options.form_bins),
                len(group.matches),
                group.players,
                group.wins,
                100 * group.wins / group.players,
                group.complete_players,
                group.bounded_players,
                group.unverified_players,
                None if group.unverified_players else group.max_tail_error,
            )
            for index, group in sorted(groups.items())
            if len(group.matches) >= options.min_matches
        )
        return Report(
            (
                "from_score",
                "to_score",
                "weighted_score",
                "matches",
                "players",
                "wins",
                "win_percent",
                "complete_players",
                "bounded_players",
                "unverified_players",
                "max_tail_error",
            ),
            rows,
            Plot(
                "weighted_score",
                ("win_percent",),
                "Вероятность победы по взвешенной истории игр",
                "Взвешенный результат прошлых игр (центр интервала)",
                "Доля побед, %",
                counts="players",
                counts_label="Наблюдений игроков",
            ),
            notes=(
                f"Проверка полной доступной истории (--complete-history): {options.complete_history}; "
                f"исключено из-за неопределённого интервала веса: {incomplete}. "
                "Проверка относится к доступным данным OpenDota, а не ко всем играм Valve.",
                "Вес истории = сумма W * 0.5^N: W = +1 для победы и -1 для поражения; "
                "N = 1 для последней завершённой игры, 2 для предпоследней и т. д. "
                "Вся доступная рейтинговая история на любых героях до начала текущего матча. "
                "Текущий, будущие и ещё не завершённые матчи исключены. "
                "--history-days и --history-matches не ограничивают этот анализ.",
                f"Ограниченная погрешность (--bounded-history): {options.bounded_history}; "
                f"требуется {options.recent_games} последовательных игр. "
                "complete_players — полная доступная история, bounded_players — подтверждённый "
                "недавний участок, unverified_players — непроверенная полнота. "
                "max_tail_error — граница вклада неизвестного хвоста; при непроверенной истории пуста. "
                "Если граница погрешности пересекает интервалы X, наблюдение исключается.",
                f"Минимум игр истории: {options.min_history}; "
                f"максимум использовано: {max_history}; "
                f"наблюдений с недостаточной историей: {insufficient}. "
                f"Вес группируется в {options.form_bins} интервалов от -1 до +1 "
                "(--form-bins). Интервалы [from_score, to_score); последний включает +1. "
                "X — центр интервала; расчёт веса выполняется до группировки без округления.",
                "Наблюдение — игрок в текущем матче. win_percent = wins / players * 100. "
                "matches — число уникальных матчей; --min-matches фильтрует каждый интервал. "
                "Анонимные аккаунты исключены. Полнота истории зависит от локальной базы "
                "и доступности данных OpenDota. Наблюдения одного матча зависимы; "
                "причинный эффект не оценивается.",
                "Для загрузки всей доступной истории: "
                "python -m matchdb history --all-history --limit 100. "
                "При достижении лимита страниц повторите команду для продолжения.",
            ),
        )
