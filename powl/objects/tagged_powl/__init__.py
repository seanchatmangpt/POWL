import dataclasses as _dataclasses
import sys as _sys

from .activity import Activity
from .base import TaggedPOWL

_original_dataclass = _dataclasses.dataclass
if _sys.version_info < (3, 10):
    def _dataclass_without_slots(*args, **kwargs):
        kwargs.pop("slots", None)
        return _original_dataclass(*args, **kwargs)

    _dataclasses.dataclass = _dataclass_without_slots

try:
    from .builders import expand_frequency_tags, loop, sequence, silent_activity, xor
    from .choice_graph import ChoiceGraph
finally:
    _dataclasses.dataclass = _original_dataclass

from .partial_order import PartialOrder

__all__ = [
    "Activity",
    "ChoiceGraph",
    "PartialOrder",
    "TaggedPOWL",
    "expand_frequency_tags",
    "loop",
    "sequence",
    "silent_activity",
    "xor",
]
