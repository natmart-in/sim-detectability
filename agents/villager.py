"""A villager: identity + memory + brain + a daily plan being executed."""
from engine.clock import TICKS_PER_DAY

from .brain import PlanStep
from .memory import MemoryStream


class Villager:
    def __init__(self, spec: dict, brain, memory: MemoryStream):
        self.spec = spec
        self.name = spec["name"]
        self.first_name = spec["name"].split()[0]
        self.brain = brain
        self.memory = memory
        self.plan: list[PlanStep] = []
        self.yesterday_reflection: str | None = None

    def plan_step_at(self, tick_of_day: int) -> PlanStep:
        for step in self.plan:
            if step.start_tick <= tick_of_day < step.end_tick:
                return step
        return PlanStep(0, TICKS_PER_DAY, "pottering about at home", self.spec["home"])
