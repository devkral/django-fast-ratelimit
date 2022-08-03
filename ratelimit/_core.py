__all__ = ["decorate", "o2g", "parse_rate", "get_ratelimit"]

import re
import hashlib
import functools
import time
import base64
from typing import Any, Union, Optional
from collections.abc import Callable, Collection

from django.conf import settings
from django.http import HttpRequest
from django.core.cache import caches
from django.utils.module_loading import import_string

from .misc import (
    invertedset,
    ALL,
    RatelimitExceeded,
    Ratelimit,
    Action,
)
from . import methods as rlimit_methods

_rate = re.compile(r"(\d+)/(\d+)?([smhdw])?")


_PERIOD_MAP = {
    None: 1,  # second, falllback
    "s": 1,  # second
    "m": 60,  # minute
    "h": 3600,  # hour
    "d": 86400,  # day
    "w": 604800,  # week
}


# clear if you test multiple RATELIMIT_GROUP_HASH definitions
@functools.lru_cache()
def _get_group_hash(group: str) -> str:
    return base64.b85encode(
        hashlib.new(
            getattr(settings, "RATELIMIT_GROUP_HASH", "md5"),
            group.encode("utf-8"),
        ).digest()
    ).decode("ascii")


def _get_cache_key(group: str, hashctx, prefix: str):
    return "%(prefix)s%(group)s:%(parts)s" % {
        "prefix": prefix,
        "group": _get_group_hash(group),
        "parts": base64.b85encode(hashctx.digest()).decode("ascii"),
    }


@functools.lru_cache()
def _parse_parts(rate: tuple, methods: frozenset, hashname: str):
    if not hashname:
        hashname = getattr(settings, "RATELIMIT_KEY_HASH", "sha256")
    hasher = hashlib.new(hashname, str(rate[1]).encode("utf-8"))

    if isinstance(methods, invertedset):
        hasher.update(b"i")
    else:
        hasher.update(b"n")
    hasher.update("".join(sorted(methods)).encode("utf-8"))

    return hasher


@functools.singledispatch
def parse_rate(rate) -> tuple[int, int]:
    raise NotImplementedError


@parse_rate.register(str)
@functools.lru_cache()
def _(rate) -> tuple[int, int]:
    try:
        counter, multiplier, period = _rate.match(rate).groups()
    except AttributeError as e:
        raise ValueError("invalid rate format") from e
    counter = int(counter)
    multiplier = 1 if multiplier is None else int(multiplier)
    return counter, multiplier * _PERIOD_MAP[period]


@parse_rate.register(list)
def _(rate) -> tuple[int, int]:
    assert len(rate) == 2
    return tuple(rate)


@parse_rate.register(type(None))
@parse_rate.register(tuple)
def _(rate) -> tuple[int, int]:
    assert rate is None or len(rate) == 2
    return rate


@functools.singledispatch
def _retrieve_key_func(key):
    raise ValueError("Key type is invalid")


@_retrieve_key_func.register(str)
def _(key):
    key = key.split(":", 1)
    if "." not in key[0]:
        impname = "ratelimit.methods.%s" % key[0]
    else:
        impname = key[0]
    fun = import_string(impname)
    if len(key) == 2:
        return fun(key[1])
    if hasattr(fun, "dispatch"):
        fun = fun.dispatch(HttpRequest)
    return fun


@_retrieve_key_func.register(list)
@_retrieve_key_func.register(tuple)
def _(key):
    if "." not in key[0]:
        impname = "ratelimit.methods.%s" % key[0]
    else:
        impname = key[0]
    fun = import_string(impname)
    if len(key) > 1:
        return fun(*key[1:])
    if hasattr(fun, "dispatch"):
        fun = fun.dispatch(HttpRequest)
    return fun


@_retrieve_key_func.register(str)
def _(key):
    _key = key.split(":", 1)
    if _key[0] in rlimit_methods.__all__:
        if len(_key) == 2:
            return getattr(rlimit_methods, _key[0])(_key[1])
        else:
            return getattr(rlimit_methods, _key[0])
    else:
        raise ValueError("Invalid cache key function")


def get_ratelimit(
    group: Union[str, Callable[[HttpRequest], str]],
    key: Union[
        str, tuple, list, Callable[[HttpRequest], Union[int, bool, str]]
    ],
    rate: Union[
        str, tuple, list, Callable[[HttpRequest], Union[int, bool, str]]
    ],
    *,
    request: Optional[HttpRequest] = None,
    methods: Union[
        str, Collection, Callable[[HttpRequest, str], Union[Collection, str]]
    ] = ALL,
    action: Action = Action.PEEK,
    prefix: Optional[str] = None,
    empty_to: Union[bytes, int] = b"",
    cache: Optional[str] = None,
    hash_algo: Optional[str] = None,
    hashctx: Optional[Any] = None,
    include_reset: bool = False
):
    """
    Get ratelimit information

    Arguments:
        group {str|callable} -- [group name or callable (fun(request))]
        key {multiple} -- see Readme
        rate {multiple} -- see Readme

    Keyword Arguments:
        request {request|None} -- django request (default: {None})
        methods {collection} -- affecte http operations (default: {ALL})
        action {ratelimit.Action} --
            PEEK: only lookup
            INCREASE: count up and return result
            RESET: return former result and reset (default: {PEEK})
        prefix {str} -- cache-prefix (default: {in settings configured})
        empty_to {bytes|int} -- default if key returns None (default: {b""})
        cache {str} -- cache name (default: {None})
        hash_algo {str} -- Hash algorithm for key (default: {None})
        hashctx {hash_context} -- see README (default: {None})
        include_reset {bool} --
            add reset cache method if cache is in use (default: {False})

    Returns:
        ratelimit.Ratelimit -- ratelimit object
    """
    if callable(group):
        group = group(request)
    if callable(methods):
        methods = methods(request, group)
    assert (
        request or methods == ALL
    ), "error: no request but methods is not ALL"  # noqa: E501
    assert all(map(lambda x: x.isupper(), methods)), "error: method lowercase"
    assert isinstance(empty_to, (bool, bytes, int)), "invalid type: %s" % type(
        empty_to
    )  # noqa: E501
    # shortcut allow
    if request and request.method not in methods:
        return Ratelimit()
    if isinstance(methods, str):
        methods = {methods}
    if not isinstance(methods, frozenset):
        methods = frozenset(methods)

    if isinstance(key, (str, tuple, list)):
        key = _retrieve_key_func(key)

    if callable(key):
        key = key(request, group)
        if isinstance(key, str):
            key = key.encode("utf8")
    if key == b"":
        key = empty_to

    assert isinstance(key, (bytes, bool, int))
    # shortcuts for disabling ratelimit
    if key is False or not getattr(settings, "RATELIMIT_ENABLE", True):
        return Ratelimit()

    if callable(rate):
        rate = rate(request, group)
    rate = parse_rate(rate)

    # sidestep cache (bool is True or Result)
    if isinstance(key, int):
        return Ratelimit(group=group, limit=rate[0], request_limit=key)

    if not prefix:
        prefix = getattr(settings, "RATELIMIT_KEY_PREFIX", "frl:")
    if not cache:
        cache = getattr(settings, "RATELIMIT_DEFAULT_CACHE", "default")
    if isinstance(cache, str):
        cache = caches[cache]

    if not hashctx:
        hashctx = _parse_parts(rate, methods, hash_algo).copy()
        hashctx.update(key)
    else:
        hashctx = hashctx.copy()
        if key is not True:
            hashctx.update(key)
    cache_key = _get_cache_key(group, hashctx, prefix)

    # use a fixed window counter algorithm
    if action == Action.INCREASE:
        # start with 1 (as if increased)
        if cache.add(cache_key, 1, rate[1]):
            count = 1
        else:
            try:
                # incr does not extend cache duration
                count = cache.incr(cache_key)
            except ValueError:
                count = None
    else:
        count = cache.get(cache_key, 0)
        if action == Action.RESET:
            cache.delete(cache_key)

    return Ratelimit(
        count=count,
        limit=rate[0],
        request_limit=1 if count is None or count > rate[0] else 0,
        end=int(time.time()) + rate[1],
        group=group,
        reset=lambda: cache.delete(cache_key) if include_reset else None,
    )


def o2g(obj):
    if isinstance(obj, functools.partial):
        obj = obj.func
    if getattr(obj, "__module__", None):
        parts = [obj.__module__, obj.__qualname__]
    else:
        parts = [obj.__qualname__]
    return ".".join(parts)


def decorate(func=None, block=False, **context):
    assert context.get("key")
    assert context.get("rate")
    assert "request" not in context
    assert "inc" not in context
    if "methods" not in context:
        context["methods"] = ALL
    if "hash_algo" not in context:
        context["hash_algo"] = getattr(
            settings, "RATELIMIT_KEY_HASH", "sha256"
        )

    def _decorate(fn):
        if not context.get("group"):
            context["group"] = o2g(fn)
        if not callable(context["rate"]):
            # result is not callable too (tuple)
            context["rate"] = parse_rate(context["rate"])

        if "hashctx" not in context and not callable(context["methods"]):
            if not isinstance(context["methods"], frozenset):
                context["methods"] = frozenset(context["methods"])

            context["hashctx"] = _parse_parts(
                context["rate"], context["methods"], context["hash_algo"]
            ).copy()

            if isinstance(context["key"], bytes):
                context["hashctx"].update(context["key"])
                context["key"] = True
        if isinstance(context["key"], (str, tuple, list)):
            context["key"] = _retrieve_key_func(context["key"])

        @functools.wraps(fn)
        def _wrapper(request, *args, **kwargs):
            nrlimit = get_ratelimit(
                request=request,
                action=Action.INCREASE,
                include_reset=True,
                **context
            )
            if block and nrlimit.request_limit > 0:
                raise RatelimitExceeded(nrlimit)
            oldrlimit = getattr(request, "ratelimit", None)
            if not oldrlimit:
                setattr(request, "ratelimit", nrlimit)
            elif bool(oldrlimit.request_limit) != bool(nrlimit.request_limit):
                if nrlimit.request_limit:
                    setattr(request, "ratelimit", nrlimit)
            elif oldrlimit.end > nrlimit.end:
                nrlimit.request_limit += oldrlimit.request_limit
                setattr(request, "ratelimit", nrlimit)
            else:
                oldrlimit.request_limit += nrlimit.request_limit
            return fn(request, *args, **kwargs)

        return _wrapper

    if func:
        return _decorate(func)
    return _decorate
