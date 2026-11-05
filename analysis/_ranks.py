RANK_NAMES = (
    "Рекрут",
    "Страж",
    "Рыцарь",
    "Герой",
    "Легенда",
    "Властелин",
    "Божество",
    "Титан",
)
MEDALS = tuple((index * 10, name) for index, name in enumerate(RANK_NAMES, 1))


def rank_name(rank: int) -> str:
    if not 10 <= rank <= 80:
        return "Неизвестный ранг"
    return RANK_NAMES[rank // 10 - 1]


def rank_group(rank: int | None, *, detailed: bool = False) -> int | None:
    if rank is None or not 10 <= rank <= 80:
        return None
    return rank if detailed else rank // 10 * 10
