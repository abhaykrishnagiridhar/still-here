"""Shared data types. Immutable on purpose: build a new object instead of editing one.

Units are millimetres and degrees. Coordinates are in the arm frame
(origin at the arm base, x forward, y left, z up). See docs/protocol.md.
"""

from dataclasses import dataclass
from typing import Literal

WeightClass = Literal["light", "heavy"]
StepAction = Literal["pick", "drop"]

BOTTOM_LAYER = 1
TOP_LAYER = 2


@dataclass(frozen=True)
class Block:
    id: int
    marker_id: int
    x: float
    y: float
    layer: int
    weight_class: WeightClass = "light"
    load_bearing: bool = False
    supports: tuple[int, ...] = ()


@dataclass(frozen=True)
class HeatZone:
    x: float
    y: float
    radius: float


@dataclass(frozen=True)
class PlanStep:
    id: int
    action: StepAction
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Plan:
    plan_id: int
    steps: tuple[PlanStep, ...]
