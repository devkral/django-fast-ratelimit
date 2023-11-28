__all__ = [
    "Action",
    "invertedset",
    "ALL",
    "SAFE",
    "UNSAFE",
    "RatelimitExceeded",
    "Disabled",
    "protect_sync_only",
    "get_RATELIMIT_TRUSTED_PROXY",
    "get_ip",
]

import asyncio
import functools
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from math import inf
from typing import Literal, Optional, Union

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
    limit: Union[Literal[inf], int] = inf
    request_limit: int = 0
    end: int = 0
    cache: Optional[BaseCache] = field(
        default=None, compare=False, hash=False, repr=False
    )
    cache_key: Optional[str] = field(
        default=None, compare=False, hash=False, repr=False
    )

    def check(self, block=False):
        if self.request_limit > 0:
            if block:
                raise RatelimitExceeded(ratelimit=self)
            return False
        return True

    async def acheck(self, wait=False, block=False):
        if self.request_limit > 0:
            if wait:
                remaining_dur = self.end - int(time.time())
                if remaining_dur > 0:
                    await asyncio.sleep(remaining_dur)
            if block:
                raise RatelimitExceeded(ratelimit=self)
            return False
        return True

    @property
    def can_reset(self):
        return self.cache and self.cache_key

    def reset(self, epoch=None) -> Optional[int]:
        if not self.can_reset:
            return None
        if not epoch:
            count = self.cache.get(self.cache_key, 0)
            self.cache.delete(self.cache_key)
            return count
        else:
            return reset_epoch(epoch, self.cache, self.cache_key)

    async def areset(self, epoch=None) -> Optional[int]:
        if not self.can_reset:
            return None
        if not epoch:
            count = await self.cache.aget(self.cache_key, 0)
            await self.cache.adelete(self.cache_key)
            return count
        else:
            return await areset_epoch(epoch, self.cache, self.cache_key)

    def _decorate_intern(self, obj, name, replace):
        if replace:
            setattr(obj, name, self)
            return self
        else:
            oldrlimit = getattr(obj, name, None)
            if oldrlimit != self:
                if not oldrlimit:
                    setattr(obj, name, self)
                elif bool(oldrlimit.request_limit) != bool(self.request_limit):
                    if self.request_limit:
                        setattr(obj, name, self)
                elif oldrlimit.end > self.end:
                    self.request_limit += oldrlimit.request_limit
                    setattr(obj, name, self)
                else:
                    # oldrlimit.end <= self.end
                    oldrlimit.request_limit += self.request_limit
            return getattr(obj, name)

    def decorate_object(
        self, obj=None, *, name="ratelimit", block=False, replace=False
    ):
        if not obj:
            return functools.partial(
                self.decorate_object, name=name, block=block, replace=replace
            )
        # for decorate
        if not name:
            self.check(block=block)
            return obj
        self._decorate_intern(obj, name, replace).check(block=block)
        return obj

    async def adecorate_object(
        self, obj=None, *, name="ratelimit", wait=False, block=False, replace=False
    ):
        if not obj:
            return functools.partial(
                self.adecorate_object,
                name=name,
                wait=wait,
                block=block,
                replace=replace,
            )
        # for decorate
        if not name:
            await self.acheck(wait=wait, block=block)
            return obj
        await self._decorate_intern(obj, name, replace).acheck(wait=wait, block=block)
        return obj


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

    def __init__(self, *args, ratelimit: Ratelimit):
        self.ratelimit = ratelimit
        super().__init__(*args)


class Disabled(PermissionDenied):
    ratelimit = None

    def __init__(self, *args, ratelimit: Ratelimit):
        self.ratelimit = ratelimit
        super().__init__(*args)


@functools.lru_cache(maxsize=1)
def get_RATELIMIT_TRUSTED_PROXY() -> Union[frozenset, invertedset]:
    s = getattr(settings, "RATELIMIT_TRUSTED_PROXIES", ["unix"])
    if s == "all":
        return invertedset()
    else:
        return frozenset(s)


def protect_sync_only(fn):
    @functools.wraps(fn)
    def inner(*args):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return fn(*args)
        return loop.run_in_executor(None, fn, *args)

    return inner


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
