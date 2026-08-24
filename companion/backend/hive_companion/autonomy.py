"""Autonomy modes — how much the agent may do on its own, chosen per goal.

- approve: every mutating step waits for explicit researcher approval.
- tiered:  read-only steps run automatically; mutating steps wait.
- auto:    everything runs unattended once the plan is accepted.

The mode is stored per goal and can be switched live between steps.
"""

from __future__ import annotations

from enum import Enum


class AutonomyMode(str, Enum):
    APPROVE = "approve"
    TIERED = "tiered"
    AUTO = "auto"


MODES = [m.value for m in AutonomyMode]


def resolve_mode(value: str | None) -> AutonomyMode:
    if value and value in MODES:
        return AutonomyMode(value)
    return AutonomyMode.TIERED


def gate(mode: AutonomyMode, mutates: bool) -> str:
    """Return 'run' or 'wait_approval' for a step under this mode."""
    if not mutates:
        return "run"
    return "run" if mode is AutonomyMode.AUTO else "wait_approval"
