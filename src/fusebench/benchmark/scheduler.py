"""Deterministic paired and interleaved benchmark scheduling."""

import random
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field


class ScheduledExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    order_index: int = Field(ge=0)
    case_id: str
    system: str
    repetition: int = Field(default=0, ge=0)


def build_paired_schedule(
    case_ids: Sequence[str],
    *,
    seed: int,
    systems: tuple[str, str] = ("terra_only", "terra_jev"),
    repetition: int = 0,
) -> tuple[ScheduledExecution, ...]:
    """Keep each system pair adjacent while randomizing within-pair order."""

    if len(set(case_ids)) != len(case_ids):
        raise ValueError("schedule case IDs must be unique")
    if len(set(systems)) != 2:
        raise ValueError("paired schedule requires two distinct systems")
    generator = random.Random(seed)
    schedule: list[ScheduledExecution] = []
    for case_id in case_ids:
        pair = list(systems)
        generator.shuffle(pair)
        for system in pair:
            schedule.append(
                ScheduledExecution(
                    order_index=len(schedule),
                    case_id=case_id,
                    system=system,
                    repetition=repetition,
                )
            )
    return tuple(schedule)
