__all__ = [
    "Action",
    "invertedset",
    "ALL",
    "SAFE",
    "UNSAFE",
    "RatelimitExceeded",
]

import sys
from enum import Enum
from math import inf
from dataclasses import dataclass, field

from typing import Optional, Union
from collections.abc import Callable

from django.core.exceptions import PermissionDenied


class Action(Enum):
    PEEK = 1
    INCREASE = 2
    RESET = 3


_deco_options = {}
if sys.version_info >= (3, 10):
    _deco_options["slots"] = True


@dataclass(**_deco_options)
class Ratelimit:
    count: int = 0
    limit: Union[float, int] = inf
    request_limit: int = 0
    end: Union[float, int] = inf
    group: Optional[str] = None
    reset: Optional[Callable[[], None]] = field(
        default=None, repr=False, compare=False, hash=False
    )


class invertedset(frozenset):
    """
    Inverts a collection
    """

    def __contains__(self, item):
        return not super().__contains__(item)


ALL = invertedset([])
SAFE = frozenset(["GET", "HEAD", "OPTIONS"])
UNSAFE = invertedset(SAFE)


class RatelimitExceeded(PermissionDenied):
    ratelimit = None

    def __init__(self, ratelimit, *args):
        self.ratelimit = ratelimit
        super().__init__(*args)
