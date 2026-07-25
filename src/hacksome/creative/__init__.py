"""Compatibility exports for the Creative Ideation route."""

from hacksome.stages.ideation import creative as _implementation


__all__ = _implementation.__all__
globals().update({name: getattr(_implementation, name) for name in __all__})
