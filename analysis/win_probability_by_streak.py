from dataclasses import replace

from matchdb.dataset import MatchData

from ._base import Options, Report
from ._streak import Analysis as StreakAnalysis


class Analysis(StreakAnalysis):
    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        wins = super().run(matches, options)
        losses_analysis = StreakAnalysis()
        losses_analysis.streak_won = False
        losses = losses_analysis.run(matches, options)
        assert wins.plot is not None
        return Report(
            ("streak_length", "streak_type", *wins.columns[1:]),
            tuple(
                (row[0], label, *row[1:])
                for report, label in ((wins, "победы"), (losses, "поражения"))
                for row in report.rows
            ),
            replace(
                wins.plot,
                x="streak_length",
                series="streak_type",
                title="Вероятность победы после серии побед или поражений",
                xlabel="Длина серии перед матчем",
            ),
            notes=(*wins.notes, losses.notes[1]),
        )
