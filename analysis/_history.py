from collections import Counter, defaultdict

from matchdb.dataset import HistoryGame, MatchData, PlayerData

from ._base import ranked_matches, valid_player


def identified_players(match: MatchData) -> tuple[PlayerData, ...]:
    players = tuple(player for player in match.players if valid_player(player))
    accounts = Counter(player.account_id for player in players)
    return tuple(
        player
        for player in players
        if player.account_id is not None
        and 0 < player.account_id < 4294967295
        and accounts[player.account_id] == 1
    )


def player_histories(
    matches: tuple[MatchData, ...],
) -> dict[int, tuple[HistoryGame, ...]]:
    history: defaultdict[int, dict[int, HistoryGame]] = defaultdict(dict)
    local: defaultdict[int, dict[int, HistoryGame]] = defaultdict(dict)
    for match in ranked_matches(matches):
        if match.start_time is None or match.start_time <= 0:
            continue
        assert match.duration is not None
        for player in identified_players(match):
            assert player.account_id is not None and player.hero_id is not None
            for entry in player.history:
                history[player.account_id].setdefault(entry.match_id, entry)
            local[player.account_id][match.match_id] = HistoryGame(
                match.match_id,
                match.start_time,
                match.duration,
                player.hero_id,
                match.radiant_win == (player.player_slot < 128),
            )
    for account, games in local.items():
        history[account].update(games)
    return {
        account: tuple(
            sorted(games.values(), key=lambda game: (game.start_time, game.match_id))
        )
        for account, games in history.items()
    }


def completed_games(
    history: tuple[HistoryGame, ...], match: MatchData
) -> tuple[HistoryGame, ...]:
    assert match.start_time is not None
    return tuple(
        game
        for game in history
        if game.match_id != match.match_id
        and game.start_time + game.duration < match.start_time
    )


def recent_games(
    history: tuple[HistoryGame, ...], match: MatchData, days: int, limit: int
) -> tuple[HistoryGame, ...]:
    assert match.start_time is not None
    cutoff = match.start_time - days * 86400
    return tuple(
        game for game in completed_games(history, match) if cutoff <= game.start_time
    )[-limit:]
