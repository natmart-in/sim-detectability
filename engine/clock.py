"""Sim time. 64 ticks per sim-day, 15 sim-minutes per tick (06:00-22:00).

No wall-clock time exists anywhere in-world or in the logs: pauses, retries
and resumes leave no seam of our own making.
"""

TICKS_PER_DAY = 64
MINUTES_PER_TICK = 15
DAY_START_MINUTE = 6 * 60  # 06:00


class SimClock:
    def __init__(self, tick: int = 0):
        self.tick = tick

    @property
    def day(self) -> int:
        return self.tick // TICKS_PER_DAY + 1

    @property
    def tick_of_day(self) -> int:
        return self.tick % TICKS_PER_DAY

    @property
    def minute_of_day(self) -> int:
        return DAY_START_MINUTE + self.tick_of_day * MINUTES_PER_TICK

    @property
    def hour(self) -> float:
        return self.minute_of_day / 60

    def time_label(self) -> str:
        m = self.minute_of_day
        return f"Day {self.day}, {m // 60:02d}:{m % 60:02d}"

    def is_day_start(self) -> bool:
        return self.tick_of_day == 0

    def is_day_end(self) -> bool:
        return self.tick_of_day == TICKS_PER_DAY - 1

    def advance(self):
        self.tick += 1
