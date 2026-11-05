from collections import defaultdict
from dataclasses import dataclass, field
from math import fsum

from matchdb.dataset import MatchData

from ._base import BaseAnalysis, Options, Plot, Report, ranked_matches, valid_player
from ._history import identified_players, player_histories
from ._statistics import DISTRIBUTION_NOTE, distribution, distribution_columns
from ._weighted_history import Weight, estimate_weight, score_interval, weight_bin


@dataclass(slots=True)
class Samples:
    matches: set[int] = field(default_factory=set)
    players: int = 0
    values: list[float] = field(default_factory=list)
    complete_players: int = 0
    bounded_players: int = 0
    unverified_players: int = 0
    max_mean_tail_error: float = 0.0
    max_player_tail_error: float = 0.0


class Analysis(BaseAnalysis):
    requires_players = True

    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        metric = "mean_weight"
        title = "Средний вес участника"
        history = player_histories(matches)
        incomplete = 0
        groups: defaultdict[tuple[int, str], Samples] = defaultdict(Samples)
        skipped: defaultdict[str, int] = defaultdict(int)
        eligible_players = 0
        for match in ranked_matches(matches):
            if match.start_time is None or match.start_time <= 0:
                continue
            players = tuple(p for p in match.players if valid_player(p))
            if len(players) != 10 or len({p.player_slot for p in players}) != 10:
                continue
            scores: dict[int, Weight] = {}
            for player in identified_players(match):
                assert player.account_id is not None
                weight = estimate_weight(
                    player, match, history[player.account_id], options
                )
                if weight is not None:
                    scores[player.player_slot] = weight
                else:
                    incomplete += 1
            for player in players:
                if player.player_slot not in scores:
                    continue
                eligible_players += 1
                focal = scores[player.player_slot]
                index = weight_bin(focal, options.form_bins)
                if index is None:
                    continue
                radiant = player.player_slot < 128
                allies = [
                    p.player_slot
                    for p in players
                    if p.player_slot != player.player_slot
                    and (p.player_slot < 128) == radiant
                ]
                enemies = [
                    p.player_slot for p in players if (p.player_slot < 128) != radiant
                ]
                for team, slots in (("allies", allies), ("enemies", enemies)):
                    if any(slot not in scores for slot in slots):
                        skipped[team] += 1
                        continue
                    group = groups[index, team]
                    group.matches.add(match.match_id)
                    group.players += 1
                    weights = [scores[slot] for slot in slots]
                    inputs = [focal, *weights]
                    verified = all(weight.tail_error is not None for weight in inputs)
                    complete = all(weight.complete for weight in inputs)
                    group.complete_players += complete
                    group.bounded_players += verified and not complete
                    group.unverified_players += not verified
                    group.max_mean_tail_error = max(
                        group.max_mean_tail_error,
                        fsum(weight.tail_error or 0 for weight in weights) / len(slots),
                    )
                    group.max_player_tail_error = max(
                        group.max_player_tail_error, focal.tail_error or 0
                    )
                    value = fsum(weight.value for weight in weights)
                    group.values.append(value / len(slots))
        rows = tuple(
            (
                *score_interval(index, options.form_bins),
                team,
                len(group.matches),
                group.players,
                4 if team == "allies" else 5,
                group.complete_players,
                group.bounded_players,
                group.unverified_players,
                None if group.unverified_players else group.max_player_tail_error,
                None if group.unverified_players else group.max_mean_tail_error,
                *distribution(group.values),
            )
            for (index, team), group in sorted(groups.items())
            if len(group.matches) >= options.min_matches
        )
        return Report(
            (
                "from_score",
                "to_score",
                "weighted_score",
                "team",
                "matches",
                "players",
                "team_size",
                "complete_players",
                "bounded_players",
                "unverified_players",
                "max_player_tail_error",
                "max_mean_tail_error",
                *distribution_columns(metric),
            ),
            rows,
            Plot(
                "weighted_score",
                distribution_columns(metric),
                f"{title} союзников и врагов по весу игрока",
                "Вес игрока (центр интервала)",
                title,
                kind="distribution",
                series="team",
                counts="players",
                counts_label="Наблюдений игроков",
            ),
            notes=(
                DISTRIBUTION_NOTE,
                f"Проверка полной доступной истории (--complete-history): {options.complete_history}; "
                f"исключено из-за незавершённой загрузки: {incomplete}. "
                "Проверка относится к доступным данным OpenDota, а не ко всем играм Valve.",
                "Вес каждого участника = сумма W * 0.5^N по всей доступной "
                "предыдущей рейтинговой истории: победа W = +1, поражение W = -1, "
                "последняя игра N = 1. Текущая игра и матчи, не завершённые до её начала, "
                "исключены. --history-days и --history-matches не ограничивают историю.",
                "allies — четыре союзника без самого игрока; enemies — пять врагов. "
                "Требуется история всех участников соответствующей группы. "
                "mean_weight — сумма весов группы, делённая на число её участников. "
                "Показаны медиана и квантили распределения по наблюдениям. "
                "Для союзников и врагов выборки независимы; неизвестные веса не заменяются нулями.",
                f"Ограниченная погрешность (--bounded-history): {options.bounded_history}; "
                f"требуется {options.recent_games} последовательных игр каждого участника. "
                "complete_players / bounded_players / unverified_players различают полноту входных весов. "
                "Границы погрешности хвоста для X и среднего веса вынесены в CSV; "
                "при непроверенной истории пусты. Неопределённый интервал X исключается.",
                f"Минимум игр истории каждого участника: {options.min_history}; "
                f"интервалов веса игрока: {options.form_bins} (--form-bins). "
                f"Игроков-матчей с известным весом: {eligible_players}; "
                f"исключено неполных групп союзников: {skipped['allies']}; "
                f"врагов: {skipped['enemies']}. "
                "Учитываются только матчи с десятью игровыми слотами и героями.",
                "players — наблюдения игроков; matches — уникальные матчи. "
                "--min-matches фильтрует интервалы отдельно для союзников и врагов. "
                "История может быть неполной. Наблюдения одного матча зависимы; "
                "причинный эффект не оценивается.",
                "Для дополнения истории: python -m matchdb history --all-history --limit 100.",
            ),
        )
