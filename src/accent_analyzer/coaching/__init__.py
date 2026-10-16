"""Coaching content library and recommendation engine."""

from accent_analyzer.coaching.engine import Recommendation, recommend
from accent_analyzer.coaching.library import ACCENTS, Module, load_library

__all__ = ["ACCENTS", "Module", "Recommendation", "load_library", "recommend"]
