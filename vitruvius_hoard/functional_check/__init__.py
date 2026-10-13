"""Vitruvius's owned functional page checker, measuring real browser behavior."""
from .qa import FAILED, PASSED, UNKNOWN, QA, Result
from .run import check, look
from .surface import Case, Control, Surface, plan

__version__ = "1.0.0"
__all__ = ["check", "look", "plan", "QA", "Result", "Case", "Control", "Surface", "PASSED", "FAILED", "UNKNOWN"]
