__all__ = [
    "Action",
    "invertedset",
    "ALL",
    "SAFE",
    "UNSAFE",
    "RatelimitExceeded",
    "Disabled",
    "get_RATELIMIT_TRUSTED_PROXY",
    "get_ip",
]

import functools
import re
import sys
from dataclasses import dataclass
from enum import Enum
from math import inf
from typing import Optional, Union

from django.conf import settings
from django.core.cache import BaseCache
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from ._epoch import areset_epoch, reset_epoch


class Action(Enum):
    PEEK = 1
    INCREASE = 2
    RESET = 3
    RESET_EPOCH = 4


_deco_options = {}
if sys.version_info >= (3, 10):
    _deco_options["slots"] = True


@dataclass(**_deco_options)
class Ratelimit:
    group: str
    count: int = 0
    limit: Union[float, int] = inf
    request_limit: int = 0
    end: Union[float, int] = 0
    cache: Optional[BaseCache] = None
    cache_key: Optional[str] = None

    @property
    def can_reset(self):
        return self.cache and self.cache_key

    def reset(self, epoch=None) -> Optional[int]:
        if not self.can_reset:
            return None
        if not epoch:
            return self.cache.delete(self.cache_key)
        else:
            return reset_epoch(epoch, self.cache, self.cache_key)

    async def areset(self, epoch=None) -> Optional[int]:
        if not self.can_reset:
            return None
        if not epoch:
            return await self.cache.adelete(self.cache_key)
        else:
            return await areset_epoch(epoch, self.cache, self.cache_key)


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

    def __init__(self, ratelimit: Ratelimit, *args):
        self.ratelimit = ratelimit
        super().__init__(*args)


class Disabled(PermissionDenied):
    ratelimit = None

    def __init__(self, ratelimit: Ratelimit, *args):
        self.ratelimit = ratelimit
        super().__init__(*args)


@functools.lru_cache(maxsize=1)
def get_RATELIMIT_TRUSTED_PROXY() -> frozenset:
    s = getattr(settings, "RATELIMIT_TRUSTED_PROXIES", ["unix"])
    if s == "all":
        return invertedset()
    else:
        return frozenset(s)


_forwarded_regex = re.compile(r'for="?([^";, ]+)', re.IGNORECASE)
_http_x_forwarded_regex = re.compile(r'[ "]*([^";, ]+)')
_ip6_port_cleanup_regex = re.compile(r"(?<=\]):[0-9]+$")
_ip4_port_cleanup_regex = re.compile(r":[0-9]+$")


def get_ip(request: HttpRequest):
    client_ip = request.META.get("REMOTE_ADDR", "") or "unix"
    if client_ip in get_RATELIMIT_TRUSTED_PROXY():
        try:
            ip_matches = _forwarded_regex.search(request.META["HTTP_FORWARDED"])
            client_ip = ip_matches[1]
        except KeyError:
            try:
                ip_matches = _http_x_forwarded_regex.search(
                    request.META["HTTP_X_FORWARDED_FOR"]
                )
                client_ip = ip_matches[1]
            except KeyError:
                pass
    if client_ip == "testclient":  # starlite test client
        client_ip = getattr(
            settings,
            "RATELIMIT_TESTCLIENT_FALLBACK",
            "::1",
        )
    if client_ip in {"unix", "invalid"}:
        raise ValueError("Could not determinate ip address")
    if "." in client_ip and client_ip.count(":") <= 1:
        client_ip = _ip4_port_cleanup_regex.sub("", client_ip)
    else:
        client_ip = _ip6_port_cleanup_regex.sub("", client_ip).strip("[]")

    return client_ip
