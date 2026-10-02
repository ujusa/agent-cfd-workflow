"""Shared vocabulary for every validation gate. Plan section 26: a stage may
emit only PASSED, FAILED, or BLOCKED -- never a vague state."""
from __future__ import annotations

from typing import Literal

GateStatus = Literal["PASSED", "FAILED", "BLOCKED"]
