__all__ = ["invertedset", "ALL", "SAFE", "UNSAFE", "RatelimitExceeded"]

from django.core.exceptions import PermissionDenied


class invertedset(frozenset):
    def __contains__(self, item):
        return not super().__contains__(item)


ALL = invertedset([])
SAFE = frozenset(['GET', 'HEAD', 'OPTIONS'])
UNSAFE = invertedset(SAFE)


class RatelimitExceeded(PermissionDenied):
    ratelimit = None

    def __init__(self, ratelimit, *args):
        self.ratelimit = ratelimit
        super().__init__(*args)
