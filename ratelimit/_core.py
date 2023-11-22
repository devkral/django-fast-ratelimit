__all__ = ["decorate", "o2g", "parse_rate", "get_ratelimit", "aget_ratelimit"]

import asyncio
import base64
import functools
import hashlib
import re
import time
from collections.abc import Callable, Collection
from inspect import isawaitable, iscoroutinefunction
from typing import Any, Awaitable, Optional, Union

from django.conf import settings
from django.core.cache import caches
from django.http import HttpRequest
from django.utils.module_loading import import_string

from . import methods as rlimit_methods
from ._epoch import areset_epoch, epoch_call_count, reset_epoch
from .misc import ALL, Action, Disabled, Ratelimit, invertedset

key_type = Union[str, tuple, list, bytes, int, bool]
rate_out_type = Union[str, tuple, list]

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


def _check_rate(fn):
    @functools.wraps(fn)
    def _wrapper(*args):
        rate = fn(*args)
        assert (
            isinstance(rate, tuple) and len(rate) == 2 and rate[0] >= 0 and rate[1] > 0
        ), f"invalid rate detected: {rate}, input: {args}"
        return rate

    return _wrapper


@_check_rate
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
    return tuple(rate)


@parse_rate.register(tuple)
def _(rate) -> tuple[int, int]:
    return rate


@functools.singledispatch
def _retrieve_key_func(key):
    raise ValueError("Key type is invalid")


@_retrieve_key_func.register(str)
def _(key):
    key = key.split(":", 1)
    if "." not in key[0]:
        assert not key[0].startswith("_"), "should not start with _"
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
    *,
    group: Union[str, Callable[[HttpRequest], str]],
    key: Union[
        key_type,
        Callable[[HttpRequest], key_type],
    ],
    rate: Union[rate_out_type, Callable[[HttpRequest, str], rate_out_type]],
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
    epoch: Optional[Union[object, int]] = None,
) -> Ratelimit:
    """
    Get ratelimit information

    Keyword Arguments:
        group {str|callable} -- [group name or callable (fun(request))]
        key {multiple} -- see Readme
        rate {multiple} -- see Readme
        request {request|None} -- django request (default: {None})
        methods {collection} -- affecte http operations (default: {ALL})
        action {ratelimit.Action} --
            PEEK: only lookup
            INCREASE: count up and return result
            RESET: return former result and reset
            RESET_EPOCH: return count before reset of epoch.
                         If neither epoch nor request is given like peek (default: {PEEK})
        prefix {str} -- cache-prefix (default: {in settings configured})
        empty_to {bytes|int} -- default if key returns None (default: {b""})
        cache {str} -- cache name (default: {None})
        hash_algo {str} -- Hash algorithm for key (default: {None})
        hashctx {hash_context} -- see README (default: {None})
        epoch {object|int} -- see README (default: None)


    Returns:
        ratelimit.Ratelimit -- ratelimit object
    """
    if not epoch:
        epoch = request
    if callable(group):
        group = group(request)
    if callable(methods):
        methods = methods(request, group)
    assert request or methods == ALL, "error: no request but methods is not ALL"
    assert all(map(lambda x: x.isupper(), methods)), "error: method lowercase"
    if isinstance(methods, str):
        methods = {methods}
    if not isinstance(methods, frozenset):
        methods = frozenset(methods)
    # shortcut allow
    if request and request.method not in methods:
        return Ratelimit(group=group, end=0)

    if isinstance(key, (str, tuple, list)):
        key = _retrieve_key_func(key)

    if callable(key):
        key = key(request, group)
        if isinstance(key, str):
            key = key.encode("utf8")
    assert not isawaitable(key), "cannot use async in sync method %s" % key
    assert isinstance(empty_to, (bool, bytes, int)), "invalid type: %s" % type(empty_to)
    if key == b"":
        key = empty_to

    assert isinstance(key, (bytes, bool, int))
    # shortcuts for disabling ratelimit
    if key is False or not getattr(settings, "RATELIMIT_ENABLE", True):
        return Ratelimit(group=group, end=0)

    if callable(rate):
        rate = rate(request, group)
    rate = parse_rate(rate)
    # if rate is 0 or None, always block and sidestep cache
    if not rate[0]:
        raise Disabled(
            "disabled by rate is None or 0",
            ratelimit=Ratelimit(group=group, limit=rate[0], request_limit=1, end=0),
        )

    # sidestep cache (bool maps to int)
    if isinstance(key, int):
        return Ratelimit(
            group=group,
            limit=rate[0],
            request_limit=key,
            end=int(time.time()) + rate[1],
        )

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
        epoch_call_count(epoch, cache_key)
        # start with 1 (as if increased)
        if cache.add(cache_key, 1, rate[1]):
            count = 1
        else:
            try:
                # incr does not extend cache duration
                count = cache.incr(cache_key)
            except ValueError:
                count = None
    elif action == Action.RESET_EPOCH and epoch:
        count = cache.get(cache_key, 0)
        reset_epoch(epoch, cache, cache_key)

    else:
        count = cache.get(cache_key, 0)
        if action == Action.RESET:
            cache.delete(cache_key)

    return Ratelimit(
        count=count,
        limit=rate[0],
        request_limit=1 if count is None or count > rate[0] else 0,
        # use jitter of the former calls for end
        end=int(time.time()) + rate[1],
        group=group,
        cache=cache,
        cache_key=cache_key,
    )


async def aget_ratelimit(
    *,
    group: Union[
        str,
        Awaitable[str],
        Callable[[HttpRequest], Union[Awaitable[str], str]],
    ],
    key: Union[
        key_type,
        Awaitable[key_type],
        Callable[[HttpRequest], Union[Awaitable[key_type], key_type]],
    ],
    rate: Union[
        rate_out_type,
        Awaitable[rate_out_type],
        Callable[[HttpRequest, str], Union[Awaitable[rate_out_type], rate_out_type]],
    ],
    request: Optional[HttpRequest] = None,
    methods: Union[
        str,
        Collection,
        Callable[
            [HttpRequest, str],
            Union[Collection, str],
        ],
    ] = ALL,
    action: Action = Action.PEEK,
    prefix: Optional[str] = None,
    empty_to: Union[bytes, int] = b"",
    cache: Optional[str] = None,
    hash_algo: Optional[str] = None,
    hashctx: Optional[Any] = None,
    wait: bool = False,
    epoch: Optional[Union[int, object]] = None,
) -> Awaitable[Ratelimit]:
    """
    Get ratelimit information

    Keyword Arguments:
        group {str|callable} -- [group name or callable (fun(request))]
        key {multiple} -- see Readme
        rate {multiple} -- see Readme
        request {request|None} -- django request (default: {None})
        methods {collection} -- affecte http operations (default: {ALL})
        action {ratelimit.Action} --
            PEEK: only lookup
            INCREASE: count up and return result
            RESET: return former result and reset (default: {PEEK})
            RESET_EPOCH: return count before reset of epoch.
                        If neither epoch nor request is given like peek (default: {PEEK})
        prefix {str} -- cache-prefix (default: {in settings configured})
        empty_to {bytes|int} -- default if key returns None (default: {b""})
        cache {str} -- cache name (default: {None})
        hash_algo {str} -- Hash algorithm for key (default: {None})
        hashctx {hash_context} -- see README (default: {None})
        epoch {object|int} -- see README (default: None)

    Returns:
        Awaitable[ratelimit.Ratelimit] -- ratelimit object
    """
    if not epoch:
        epoch = request
    if callable(group):
        group = group(request)

    if isawaitable(group):
        group = await group
    if callable(methods):
        methods = methods(request, group)

    if isawaitable(methods):
        methods = await methods
    assert request or methods == ALL, "error: no request but methods is not ALL"
    assert all(map(lambda x: x.isupper(), methods)), "error: method lowercase"
    if isinstance(methods, str):
        methods = {methods}
    if not isinstance(methods, frozenset):
        methods = frozenset(methods)
    # shortcut allow
    if request and request.method not in methods:
        return Ratelimit(group=group, end=0)

    if isinstance(key, (str, tuple, list)):
        key = _retrieve_key_func(key)

    if callable(key):
        key = key(request, group)

    if isawaitable(key):
        key = await key

    if isinstance(key, str):
        key = key.encode("utf8")
    assert isinstance(empty_to, (bool, bytes, int)), "invalid type: %s" % type(empty_to)

    if key == b"":
        key = empty_to

    assert isinstance(key, (bytes, bool, int)), f"{key!r}: {type(key)}"
    # shortcuts for disabling ratelimit
    if key is False or not getattr(settings, "RATELIMIT_ENABLE", True):
        return Ratelimit(group=group, end=0)

    if callable(rate):
        rate = rate(request, group)

    if isawaitable(rate):
        rate = await rate
    rate = parse_rate(rate)
    # if rate is 0 or None, always block and sidestep cache
    if not rate[0]:
        raise Disabled(
            "disabled by rate is None or 0",
            ratelimit=Ratelimit(group=group, limit=rate[0], request_limit=1, end=0),
        )

    # sidestep cache (bool maps to int)
    if isinstance(key, int):
        if wait and key > 0:
            await asyncio.sleep(rate[1])
        return Ratelimit(
            group=group,
            limit=rate[0],
            request_limit=key,
            end=int(time.time()) + rate[1],
        )

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
        epoch_call_count(epoch, cache_key)
        # start with 1 (as if increased)
        if await cache.aadd(cache_key, 1, rate[1]):
            count = 1
        else:
            try:
                # incr does not extend cache duration
                count = await cache.aincr(cache_key)
            except ValueError:
                count = None
    elif action == Action.RESET_EPOCH and epoch:
        count = await cache.aget(cache_key, 0)
        await areset_epoch(epoch, cache, cache_key)
    else:
        count = await cache.aget(cache_key, 0)
        if action == Action.RESET:
            await cache.adelete(cache_key)

    return Ratelimit(
        count=count,
        limit=rate[0],
        request_limit=1 if count is None or count > rate[0] else 0,
        # use jitter of the former calls for end
        end=int(time.time()) + rate[1],
        group=group,
        cache=cache,
        cache_key=cache_key,
    )


def o2g(obj):
    if isinstance(obj, functools.partial):
        obj = obj.func
    if getattr(obj, "__module__", None):
        parts = [obj.__module__, obj.__qualname__]
    else:
        parts = [obj.__qualname__]
    return ".".join(parts)


def decorate(func: Optional[Callable] = None, **context):
    assert context.get("key")
    assert context.get("rate")
    assert "request" not in context
    assert "action" not in context
    block = context.pop("block", False)
    replace = context.pop("replace", False)
    decorate_name = context.pop("decorate_name", "ratelimit")
    if "methods" not in context:
        context["methods"] = ALL
    if "hash_algo" not in context:
        context["hash_algo"] = getattr(settings, "RATELIMIT_KEY_HASH", "sha256")

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
        fntocheck = fn
        if hasattr(fntocheck, "func"):
            fntocheck = fntocheck.func
        if hasattr(fntocheck, "__func__"):
            fntocheck = fntocheck.__func__
        if iscoroutinefunction(fntocheck):
            wait = context.pop("wait", False)

            @functools.wraps(fn)
            async def _wrapper(request, *args, **kwargs):
                try:
                    nrlimit = await aget_ratelimit(
                        request=request,
                        action=Action.INCREASE,
                        **context,
                    )
                except Disabled as exc:
                    # don't pass wait or block both are dangerous in this context
                    await exc.ratelimit.adecorate_object(
                        request, name=decorate_name, replace=replace
                    )
                    raise exc
                await nrlimit.adecorate_object(
                    request,
                    name=decorate_name,
                    wait=wait,
                    block=block,
                    replace=replace,
                )
                return await fn(request, *args, **kwargs)

            return _wrapper

        else:

            @functools.wraps(fn)
            def _wrapper(request, *args, **kwargs):
                # one level above with method_decorator a non-async wrapper
                # is created and discarded, so check only on the first call
                assert (
                    "wait" not in context
                ), '"wait" is only for async functions/methods supported'
                try:
                    nrlimit = get_ratelimit(
                        request=request,
                        action=Action.INCREASE,
                        **context,
                    )
                except Disabled as exc:
                    # don't pass block it is dangerous in this context
                    exc.ratelimit.decorate_object(
                        request, name=decorate_name, replace=replace
                    )
                    raise exc
                nrlimit.decorate_object(
                    request, name=decorate_name, block=block, replace=replace
                )
                return fn(request, *args, **kwargs)

            return _wrapper

    if func:
        return _decorate(func)
    return _decorate
