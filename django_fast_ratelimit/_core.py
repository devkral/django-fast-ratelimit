__all__ = ["decorate", "o2g", "parse_rate", "get_ratelimit", "aget_ratelimit"]

import asyncio
import base64
import functools
import hashlib
import re
import time
import warnings
from collections.abc import Callable, Collection
from importlib import import_module
from inspect import isawaitable
from typing import Any, Awaitable, Final, Optional, Union

from django.conf import settings
from django.core.cache import caches
from django.http import HttpRequest

from ._epoch import areset_epoch, epoch_call_count, reset_epoch
from .misc import ALL, Action, Disabled, MissingRate, Ratelimit, invertedset

key_type: Final = Union[str, tuple, list, bytes, int, bool]
rate_out_type: Final = Union[str, tuple, list]

_rate: Final = re.compile(r"(\d+)/(\d+)?([smhdw])?")


_missing_rate_sentinel: Final = object()
_missing_rate_tuple: Final = (_missing_rate_sentinel, 1)

_PERIOD_MAP: Final = {
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


@functools.singledispatch
def parse_rate(rate) -> tuple[int, int]:
    raise NotImplementedError


@parse_rate.register(str)
@functools.lru_cache()
@_check_rate
def _(rate) -> tuple[int, int]:
    try:
        counter, multiplier, period = _rate.match(rate).groups()
    except AttributeError as e:
        raise ValueError("invalid rate format") from e
    counter = int(counter)
    multiplier = 1 if multiplier is None else int(multiplier)
    return counter, multiplier * _PERIOD_MAP[period]


@parse_rate.register(list)
@_check_rate
def _(rate) -> tuple[int, int]:
    return tuple(rate)


@parse_rate.register(tuple)
@_check_rate
def _(rate) -> tuple[int, int]:
    return rate


@parse_rate.register(type(None))
def _(rate) -> tuple[int, int]:
    return _missing_rate_tuple


@functools.lru_cache(maxsize=32, typed=False)
def hardened_import_string(dotted_path):
    """check also __all__ for intended imports"""
    module_path, fn_name = dotted_path.rsplit(".", 1)
    module = import_module(module_path)
    if hasattr(module, "__all__"):
        if fn_name not in module.__all__:
            raise ValueError(f"__all__ does not contain {fn_name}")
    elif fn_name.startswith("_"):
        raise ValueError("should not start with _ (except when in __all__)")
    return getattr(module, fn_name)


@functools.singledispatch
def _retrieve_key_func(key):
    raise ValueError("Key type is invalid")


@_retrieve_key_func.register(list)
@_retrieve_key_func.register(tuple)
def _(key):
    if "." not in key[0]:
        impname = "django_fast_ratelimit.methods.%s" % key[0]
    else:
        impname = key[0]
    fun = hardened_import_string(impname)
    if len(key) > 1:
        return fun(*key[1:])
    if hasattr(fun, "dispatch"):
        fun = fun.dispatch(HttpRequest)
    return fun


@_retrieve_key_func.register(str)
def _(key):
    return _retrieve_key_func(key.split(":", 1))


@functools.lru_cache(maxsize=1, typed=True)
def _get_RATELIMIT_ENABLED(settings):
    enabled = getattr(settings, "RATELIMIT_ENABLED", None)
    if enabled is not None:
        return enabled

    enabled = getattr(settings, "RATELIMIT_ENABLE", None)
    if enabled is not None:
        warnings.warn("deprecated, use RATELIMIT_ENABLED instead", DeprecationWarning)
        return enabled
    return True


def get_ratelimit(
    *,
    group: Union[str, Callable[[Optional[HttpRequest], Action], str]],
    key: Union[
        key_type,
        Callable[[Optional[HttpRequest], str, Action], key_type],
    ],
    rate: Optional[
        Union[
            rate_out_type, Callable[[Optional[HttpRequest], str, Action], rate_out_type]
        ]
    ] = None,
    request: Optional[HttpRequest] = None,
    methods: Union[
        str,
        Collection,
        Callable[[Optional[HttpRequest], str, Action], Union[Collection, str]],
    ] = ALL,
    action: Action = Action.PEEK,
    prefix: Optional[str] = None,
    empty_to: Union[bytes, int] = b"",
    cache: Optional[str] = None,
    hash_algo: Optional[str] = None,
    hashctx: Optional[Any] = None,
    epoch: Optional[Union[object, int]] = None,
    _fail_count=0,
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
    if not _get_RATELIMIT_ENABLED(settings):
        return Ratelimit(group=group, end=0)
    if not epoch:
        epoch = request
    if callable(group):
        group = group(request, action)
    if callable(methods):
        methods = methods(request, group, action)
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

    if callable(rate):
        rate = rate(request, group, action)
    rate = parse_rate(rate)

    if callable(key):
        key = key(request, group, action, None if rate is _missing_rate_tuple else rate)
        if isinstance(key, str):
            key = key.encode("utf8")
    assert not isawaitable(key), "cannot use async in sync method %s" % key
    assert isinstance(empty_to, (bool, bytes, int)), "invalid type: %s" % type(empty_to)
    if key == b"":
        key = empty_to

    assert isinstance(key, (bytes, bool, int))
    # shortcuts for disabling ratelimit
    if key is False:
        return Ratelimit(group=group, end=0)

    if not rate[0]:
        # if rate is 0, always block and sidestep cache
        raise Disabled(
            "disabled by rate is 0",
            ratelimit=Ratelimit(group=group, limit=rate[0], request_limit=1, end=0),
        )

    # sidestep cache (bool maps to int)
    if key is not True and isinstance(key, int):
        return Ratelimit(
            group=group,
            limit=rate[0],
            request_limit=key,
            end=int(time.time()) + rate[1],
        )
    if rate[0] is _missing_rate_sentinel:
        raise MissingRate(
            "rate argument is missing or None and the key (function) doesn't sidestep cache"
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
    expired = cache.get("%s_expire" % cache_key, None)
    # have some jitter yet, synchronize upcoming timestamps
    cur_time = int(time.time())
    is_expired = False
    if not expired or expired < cur_time:
        cache.delete_many([cache_key, "%s_expire" % cache_key])
        is_expired = True

    # use a fixed window counter algorithm
    if action == Action.INCREASE:
        epoch_call_count(epoch, cache_key)
        # start with 1 (as if increased)
        if cache.add(cache_key, 1, rate[1]):
            cache.set("%s_expire" % cache_key, cur_time + rate[1], rate[1])
            count = 1
        else:
            try:
                # incr does not extend cache duration
                count = cache.incr(cache_key)
            except ValueError:
                # not in cache, but should be in cache, race condition
                if _fail_count >= 3:
                    raise ValueError("buggy cache or racing cache clear")
                return get_ratelimit(
                    request=request,
                    epoch=epoch,
                    hashctx=hashctx,
                    key=True,
                    rate=rate,
                    action=action,
                    group=group,
                    prefix=prefix,
                    cache=cache,
                    _fail_count=_fail_count + 1,
                )
    elif is_expired:
        # shortcut, we know the cache is now empty
        count = 0
    elif action == Action.RESET_EPOCH and epoch:
        count = cache.get(cache_key, 0)
        reset_epoch(epoch, cache, cache_key)

    else:
        count = cache.get(cache_key, 0)
        if action == Action.RESET:
            cache.delete_many([cache_key, "%s_expire" % cache_key])

    return Ratelimit(
        count=count,
        limit=rate[0],
        request_limit=1 if count > rate[0] else 0,
        end=cur_time + rate[1],
        group=group,
        cache=cache,
        cache_key=cache_key,
    )


async def aget_ratelimit(
    *,
    group: Union[
        str,
        Awaitable[str],
        Callable[[Optional[HttpRequest], Action], Union[Awaitable[str], str]],
    ],
    key: Union[
        key_type,
        Awaitable[key_type],
        Callable[
            [Optional[HttpRequest], str, Action], Union[Awaitable[key_type], key_type]
        ],
    ],
    rate: Optional[
        Union[
            rate_out_type,
            Awaitable[rate_out_type],
            Callable[
                [Optional[HttpRequest], str, Action],
                Union[Awaitable[rate_out_type], rate_out_type],
            ],
        ]
    ] = None,
    request: Optional[HttpRequest] = None,
    methods: Union[
        str,
        Collection,
        Callable[
            [Optional[HttpRequest], str, Action],
            Union[Collection, str],
        ],
    ] = ALL,
    action: Action = Action.PEEK,
    prefix: Optional[str] = None,
    empty_to: Union[bytes, int] = b"",
    cache: Optional[str] = None,
    hash_algo: Optional[str] = None,
    hashctx: Optional[Any] = None,
    epoch: Optional[Union[int, object]] = None,
    _fail_count=0,
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
    if not _get_RATELIMIT_ENABLED(settings):
        return Ratelimit(group=group, end=0)
    if not epoch:
        epoch = request
    if callable(group):
        group = group(request, action)

    if isawaitable(group):
        group = await group
    if callable(methods):
        methods = methods(request, group, action)

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

    if callable(rate):
        rate = rate(request, group)

    if isawaitable(rate):
        rate = await rate
    rate = parse_rate(rate)

    if callable(key):
        key = key(request, group, action, None if rate is _missing_rate_tuple else rate)

    if isawaitable(key):
        key = await key

    if isinstance(key, str):
        key = key.encode("utf8")
    assert isinstance(empty_to, (bool, bytes, int)), "invalid type: %s" % type(empty_to)

    if key == b"":
        key = empty_to

    assert isinstance(key, (bytes, bool, int)), f"{key!r}: {type(key)}"
    # shortcuts for disabling ratelimit
    if key is False:
        return Ratelimit(group=group, end=0)
    # if rate is 0, always block and sidestep cache
    if not rate[0]:
        raise Disabled(
            "disabled by rate is 0",
            ratelimit=Ratelimit(group=group, limit=rate[0], request_limit=1, end=0),
        )
    # sidestep cache (bool maps to int)
    if key is not True and isinstance(key, int):
        return Ratelimit(
            group=group,
            limit=rate[0],
            request_limit=key,
            end=int(time.time()) + rate[1],
        )
    if rate[0] is _missing_rate_sentinel:
        raise MissingRate(
            "rate argument is missing or None and the key (function) doesn't sidestep cache"
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
    expired = await cache.aget("%s_expire" % cache_key, None)
    is_expired = False
    # have some jitter yet, synchronize upcoming timestamps
    cur_time = int(time.time())
    if not expired or expired < cur_time:
        await cache.adelete_many([cache_key, "%s_expire" % cache_key])
        is_expired = True

    # use a fixed window counter algorithm
    if action == Action.INCREASE:
        epoch_call_count(epoch, cache_key)
        # start with 1 (as if increased)
        if await cache.aadd(cache_key, 1, rate[1]):
            await cache.aset("%s_expire" % cache_key, cur_time + rate[1], rate[1])
            count = 1
        else:
            try:
                # incr does not extend cache duration
                count = await cache.aincr(cache_key)
            except ValueError:
                # not in cache, but should be in cache, race condition
                if _fail_count >= 3:
                    raise ValueError("buggy cache or racing cache clear")
                return await aget_ratelimit(
                    request=request,
                    epoch=epoch,
                    hashctx=hashctx,
                    key=True,
                    rate=rate,
                    action=action,
                    group=group,
                    prefix=prefix,
                    cache=cache,
                    _fail_count=_fail_count + 1,
                )
    elif is_expired:
        # shortcut, we know the cache is now empty
        count = 0
    elif action == Action.RESET_EPOCH and epoch:
        count = await cache.aget(cache_key, 0)
        await areset_epoch(epoch, cache, cache_key)
    else:
        count = await cache.aget(cache_key, 0)
        if action == Action.RESET:
            await cache.adelete_many([cache_key, "%s_expire" % cache_key])

    return Ratelimit(
        count=count,
        limit=rate[0],
        # block on race condition
        request_limit=1 if count > rate[0] else 0,
        end=cur_time + rate[1],
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


async def _chain_async_decorate(
    *, request, fn, args, kwargs, context, decorate_name, replace, wait, block
):
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
    retobj = fn(request, *args, **kwargs)

    if isawaitable(retobj):
        return await retobj
    return retobj


def _chain_sync_decorate(
    *, request, fn, args, kwargs, context, decorate_name, replace, block
):
    try:
        nrlimit = get_ratelimit(
            request=request,
            action=Action.INCREASE,
            **context,
        )
    except Disabled as exc:
        # don't pass wait or block both are dangerous in this context
        exc.ratelimit.decorate_object(request, name=decorate_name, replace=replace)
        raise exc
    nrlimit.decorate_object(
        request,
        name=decorate_name,
        block=block,
        replace=replace,
    )
    return fn(request, *args, **kwargs)


def decorate(func: Optional[Callable] = None, **context):
    assert context.get("key")
    assert "request" not in context
    assert "action" not in context
    block = context.pop("block", False)
    replace = context.pop("replace", False)
    force_async = context.pop("force_async", None)
    wait = context.pop("wait", False)
    if force_async is None and wait:
        force_async = True
    decorate_name = context.pop("decorate_name", "ratelimit")
    if "methods" not in context:
        context["methods"] = ALL
    if not callable(context["methods"]):
        if isinstance(context["methods"], str):
            context["methods"] = {context["methods"]}
        if not isinstance(context["methods"], frozenset):
            context["methods"] = frozenset(context["methods"])
    if "hash_algo" not in context:
        context["hash_algo"] = getattr(settings, "RATELIMIT_KEY_HASH", "sha256")
    _rate = context.get("rate", None)
    if _rate is None:
        # we cannot use parse rate yet because of check_rate doesn't accept the sentinal
        context["rate"] = _rate
    elif not callable(_rate):
        # result is not callable too (tuple)
        context["rate"] = parse_rate(_rate)
    # rate is now set in context and can be used without issues

    if (
        "hashctx" not in context
        and context["rate"] is not None
        and not callable(context["methods"])
        and not callable(context["rate"])
    ):
        context["hashctx"] = _parse_parts(
            context["rate"], context["methods"], context["hash_algo"]
        ).copy()

        if isinstance(context["key"], bytes):
            context["hashctx"].update(context["key"])
            context["key"] = True
    if isinstance(context["key"], (str, tuple, list)):
        context["key"] = _retrieve_key_func(context["key"])

    def _decorate(fn):
        if not context.get("group"):
            context["group"] = o2g(fn)

        @functools.wraps(fn)
        def _wrapper(request, *args, **kwargs):
            # one level above with method_decorator a non-async wrapper
            # is created and discarded, so check only on the first call
            try:
                asyncio.get_running_loop()
                is_async = True
            except RuntimeError:
                is_async = False
            assert (
                not force_async or is_async
            ), "non async context and force_async specified or wait specified and force_async != False"
            if is_async:
                return _chain_async_decorate(
                    request=request,
                    fn=fn,
                    args=args,
                    kwargs=kwargs,
                    context=context,
                    decorate_name=decorate_name,
                    replace=replace,
                    wait=wait,
                    block=block,
                )
            else:
                return _chain_sync_decorate(
                    request=request,
                    fn=fn,
                    args=args,
                    kwargs=kwargs,
                    context=context,
                    decorate_name=decorate_name,
                    replace=replace,
                    block=block,
                )

        return _wrapper

    if func:
        return _decorate(func)
    return _decorate
