def rank_name(rank: int) -> str:
    names = (
        "Рекрут",
        "Страж",
        "Рыцарь",
        "Герой",
        "Легенда",
        "Властелин",
        "Божество",
        "Титан",
    )
    if not 10 <= rank <= 80:
        return "Неизвестный ранг"
    return names[rank // 10 - 1]
