"""Compatibility exports for the Pitch stage."""

from hacksome.stages import pitch as _implementation


__all__ = _implementation.__all__
globals().update({name: getattr(_implementation, name) for name in __all__})
