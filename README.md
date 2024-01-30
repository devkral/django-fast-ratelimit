# django-fast-ratelimit

Django-fast-ratelimit provides a secure and fast ratelimit facility based on the django caching framework.
It uses a "Fixed window counter"-algorithm based on:
https://medium.com/figma-design/an-alternative-approach-to-rate-limiting-f8a06cf7c94c

## Installation

```bash
pip install django-fast-ratelimit

```

Note: pip >= 19 is required

Note: version 5 renames package from ratelimit to django_fast_ratelimit

## usage

Apply everywhere where wanted in the django app without restrictions:

install companion library django-fast-iprestrict >= 0.6.0

Decorator:

```python
import django_fast_ratelimit as ratelimit

@ratelimit.decorate(key="ip", rate="1/s")
def expensive_func(request):
    # how many ratelimits request limiting
    if request.ratelimit["request_limit"] > 0:
        # reschedule with end of rate epoch
        return request_waiting(request.ratelimit["end"])

```

or async

```python
import django_fast_ratelimit as ratelimit
import asyncio

@ratelimit.decorate(key="ip", rate="1/s")
async def expensive_func(request):
    # how many ratelimits request limiting
    if request.ratelimit["request_limit"] > 0:
        # reschedule with end of rate epoch
        await asyncio.sleep(request.ratelimit["end"])

```

blocking Decorator (raises RatelimitError):

```python
import django_fast_ratelimit as ratelimit

@ratelimit.decorate(key="ip", rate="1/s", block=True, decorate_name="ratelimit", methods=ratelimit.UNSAFE)
def expensive_func(request):
    # how many ratelimits request limiting
    if request.ratelimit["end"] > 0:

```

decorate View (requires group):

```python
import django_fast_ratelimit as ratelimit
from django.views.generic import View
from django.utils.decorators import method_decorator


@method_decorator(ratelimit.decorate(
  key="ip", rate="1/s", block=True, methods=ratelimit.SAFE, group="required"
), name="dispatch")
class FooView(View):
    ...

```

manual

```python
import django_fast_ratelimit as ratelimit


def func(request):
    ratelimit.get_ratelimit(key="ip", rate="1/s", request=request, group="123", action=ratelimit.Action.INCREASE)
    # or only for GET
    ratelimit.get_ratelimit(
        key="ip", rate="1/s", request=request, group="123", methods="GET", action=ratelimit.Action.INCREASE
    )
    # also simple calls possible (note: key in bytes format)
    ratelimit.get_ratelimit(
        key=b"abc", rate="1/s", group="123", action=ratelimit.Action.INCREASE
    )
    # retrieve ratelimit
    rlimit = ratelimit.get_ratelimit(
        key="ip", rate="1/s", request=request, group="123"
    )
    # reset (clears internal counter)
    counter_before_reset = rlimit.reset()
    # reset epoch (resets to the start of request/epoch)
    counter_before_reset = rlimit.reset(request)
    # decrease counter by arbitary amount
    rlimit.reset(19)
    # increase counter by arbitary amount
    rlimit.reset(-19)

    # check constraints of rate
    r = ratelimit.parse_rate("1/s")  # returns tuple (amount, period)
    assert(r[1]==1)  #  assert period is 1 second
    # for simple naming use o2g (object to group)
    ratelimit.get_ratelimit(
        key=b"abc", rate=r, group=ratelimit.o2g(func), action=ratelimit.Action.INCREASE
    )

```

manual async

```python
import django_fast_ratelimit as ratelimit


async def func(request):
    # retrieve ratelimit
    rlimit = await ratelimit.aget_ratelimit(
        key="ip", rate="1/s", request=request, group="123"
    )
    # reset (clears internal counter)
    await rlimit.areset()
    # reset epoch (resets to the start of request/epoch)
    await rlimit.areset(request)
    # decrease counter by arbitary amount
    await rlimit.areset(19)
    # increase counter by arbitary amount
    await rlimit.reset(-19)
```

## parameters

### ratelimit.get_ratelimit:

-   group: group name, can be callable (fun(request, action))
-   rate: rate limit, multiple modes
    Note: if count (first argument) is 0, then it raises the Disabled exception, the second argument must be greater then 0
    -   str: default mode , specify rate in form of "1/4s" or "2/s" or "2/m"
    -   2 element tuple/list: first argument is amount, second are seconds
    -   callable: can return either string or 2 element tuple/list
        None (default): raise ValueError if key function doesn't return False to disable further execution, for django-fast-iprestrict
-   methods: set of checked methods, can be callable (fun(request, group, action)), modes:
    -   callable(request, group, action): allow dynamic
    -   ratelimit.ALL (default): all methods are checked
    -   \("HEAD", "GET"\): list of checked methods
    -   ratelimit.invertedset(["HEAD", "GET"]): inverted set of checked methods. Here: every method is checked, except HEAD, GET
-   request: ingoing request (optional if key supports it and methods=ratelimit.ALL (default))
-   key: multiple modes possible:
    -   bool: True: skip key (should only be used for baking), False: disable cache (like RATELIMIT_ENABLED=False)
    -   int: sidestep cache, value will be used for request_limit. 0 is for never blocking, >=1 blocks
    -   str: "path.to.method:argument"
    -   str: "inbuildmethod:argument" see methods for valid arguments
    -   str: "inbuildmethod" method which is ready to use for (request, group, action)
    -   tuple,list: ["method", args...]: method (can be also inbuild) with arbitary arguments
    -   bytes: static key (supports mode without request)
    -   callable: check return of function (fun(request, group, action)), return must be string (converted to bytes), bytes, bool or int (see "key" for effects)
-   empty_to: convert empty keys (b"") to parameter. Must be bytes, bool or int (see "key" for effects) (default: keep b"")
-   cache: specify cache to use, defaults to RATELIMIT_DEFAULT_CACHE setting (default: "default")
-   hash_algo: name of hash algorithm for creating cache_key (defaults to RATELIMIT_KEY_HASH setting (default: "sha256"))
    Note: group is seperately hashed
-   hashctx: optimation parameter, read the code and only use if you know what you are doing. It basically circumvents the parameter hashing and only hashes the key. If the key parameter is True even the key is skipped
-   action {ratelimit.Action}:
    -   PEEK: only lookup
    -   INCREASE: count up and return result
    -   RESET: return former result and reset
    -   RESET_EPOCH: return count after reset of epoch. If neither epoch nor request is given like peek (default: {PEEK})
-   epoch:
    -   None: (default): use request as epoch
    -   int: RESET_EPOCH resets by int. Negative int increases
    -   object: attach counter to an open object (Note: it cannot be object() directly and neither an object with slots)

returns the dataclass Ratelimit

or raises `ratelimit.Disabled` in case of the count in the rate is zero

### ratelimit.Ratelimit

Fields

-   count: how often in the window the ip whatever was calling
-   limit: limit when it should block
-   request_limit: >=1 should block or reject, 0: should accept
-   end: when does the block end
-   group: group name
-   group_key, cache: Optional, when specified reset and areset can be used, internal fields

Functions:

-   can_reset: is a reset possible or were bypasses used
-   reset: function to reset count if cache was used. When given an epoch the same as RESET_EPOCH
-   areset: async version of reset
-   check(block=False): raise RatelimitExceeded when block = True and ratelimit is exceeded
-   acheck(wait=False, block=False): raise RatelimitExceeded when block = True and ratelimit is exceeded, wait for end of ratelimit duration when wait=True
-   decorate_object(obj, name="ratelimit", block=False, replace=False): attach to object obj with name and use old limits too, pass block to check
-   adecorate_object(obj, name="ratelimit", wait=False, block=False, replace=False): attach to object obj with name and use old limits too, pass block and wait to acheck

Note: decorate_object with name=None behaves like check (except return value), the same applies for adecorate_object

arguments:

-   wait: wait until end timestamp when ratelimit was exceeded. Next call should work again, applied before block
-   block: raise a RatelimitExceeded exception
-   replace: ignore potential old ratelimit object atttached to object and just replace it

why only async methods have wait? It doesn't really block (only the userlandthread). In contrast to its sync equivalent it doesn't block the webserver significantly

Example: decorate_object

```python
import ratelimit

class Foo():
    pass

r = get_ratelimit(
    group="foo",
    rate="1/s",
    key=b"foo",
    action=ratelimit.Action.INCREASE,
)

# manual way
foo = r.decorate_object(Foo(), name="ratelimit")
if not foo.ratelimit.check():
    raise ratelimit.RatelimitExceeded("custom message", ratelimit=r)
else:
    pass
    # do cool stuff

# simplified

foo2 = r.decorate_object(Foo(), block=True)

# artistic (no point in doing so)

r.decorate_object(Foo(), name="ratelimit_is_cool").ratelimit_is_cool.check(block=True)

# like check with instance of Foo() as return value

foo3 r.decorate_object(Foo(), name=None, wait=True)

# decorate function

@r.decorate_object(block=True)
def fn():
    pass

# of course also this works

@r.decorate_object
def fn():
    pass



```

### ratelimit.aget_ratelimit:

same as `get_ratelimit` but supports async methods and has an optional parameter:
`wait`, which suspends the execution (via `asyncio.sleep`) for the time specified in rate (second argument).
This is only possible in async mode, as it would block too much in sync mode.

### ratelimit.decorate:

All of ratelimit.get_ratelimit except request. group is here optional (except for decorations with method_decorator (no access to wrapped function)).
Also supports:

-   block: should hard block with an RatelimitExceeded exception (subclass of PermissionDenied) or only annotate request with ratelimit
-   decorate_name: under what name the ratelimit is attached to the request. set to None/empty to not decorate request. Uses Ratelimit.decorate_object. Defaults to "ratelimit"
-   wait (only when async possible): suspends execution, triggers force_async when not specified
-   force_async: fail when not called in an async context, can be set to False, to not fail in sync context, or to True to fail always when in sync only context

why only async methods have wait? It doesn't really block (only the userlandthread). In contrast to its sync equivalent it doesn't block the webserver significantly

## helpers

### ratelimit.invertedset:

inverts a collection, useful for http methods

### ratelimit.get_RATELIMIT_TRUSTED_PROXY:

get the `RATELIMIT_TRUSTED_PROXIES` parsed as set

note: this function uses a cached subfunction. If you change this setting while testing you may have to call:

`ratelimit._get_RATELIMIT_TRUSTED_PROXY.cache_clear()`

### ratelimit.get_ip:

get client ip from request, using `RATELIMIT_TRUSTED_PROXIES` and forwarded headers

```python
import ratelimit

ratelimit.get_ip(request)

```

### ratelimit.o2g:

auto generate group names for method/function as input, see tests/test_decorators for more info

Example:

```python
import ratelimit


class O2gView(View):
    def get(self, request, *args, **kwargs):
        request.ratelimit2 = ratelimit.get_ratelimit(
            group=ratelimit.o2g(self.get),
            rate="1/s",
            key=b"o2gtest",
            action=ratelimit.Action.INCREASE,
        )
        if request.ratelimit2.request_limit > 0:
            return HttpResponse(status=400)
        return HttpResponse()

```

### ratelimit.RatelimitExceeded

Raised when the ratelimit was exceeded

Exception, required keyword argument is ratelimit with the ratelimit.
The next arguments are passed to the underlying standard exception class for e.g. customizing the error message

### ratelimit.Disabled

Stronger variant of RatelimitExceeded. Used for cases where limit is 0 and there is no way to pass the ratelimit.
It is a shortcut for disabling api.

Note: it is weaker than the setting `RATELIMIT_ENABLED`

Note: it isn't a subclass from RatelimitExceeded because APIs should be able to differ both cases

Note: in contrast to RatelimitExceeded it is raised in (a)get_ratelimit and when using decorate, the view function isn't called.

### ratelimit.protect_sync_only

for libraries. In case of async return protected asyncified function otherwise call library directly

## recipes

jitter:

```python
import ratelimit
import asyncio
import secrets

async def foo()

    r = await ratelimit.aget_ratelimit(
        group="foo",
        rate="1/s",
        key=b"foo",
        action=ratelimit.Action.INCREASE,
    )
    # 100ms jitter
    await asyncio.sleep(secrets.randbelow(100) / 100)
    # raise when limit reached, wait until full second jitter is eliminated in raise case as end was created before the jitter
    await r.acheck(wait=True, block=True)

```

## methods

See in methods which methods are available. Here some of them:

-   static: use static key defined by argument, if no argument was specified default to b"static", the argument is automatically converted to bytes
    Note: the conversion for non-bytes objects is str(obj).encode("utf8")
    Note: it is also possible to specify a bytes key to provide a static argument
-   ip: use ip address as key, argument: [netmask ipv4/]netmask ipv6
-   user: authenticated user primary key or b""
-   user_or_ip: use autenticated user primary key as key. If not autenticated fallback to ip, also with netmask argument
-   user_and_ip: same like user_or_ip except that the ip matching also applies for authenticated users
-   ip_exempt_user: same like user_or_ip except that authenticated users are exempted, also with netmask argument
    -   when specified with reset actions: reset the ip key with the reset action when a user was found
-   ip_exempt_privileged: same like ip_exempt_user except that authenticated users with staff or superuser flags are exempted, also with netmask argument
    -   when specified with reset actions: reset the ip key with the reset action when a privileged user was found
    ip_exempt_superuser: same like privileged just exempt only superusers
-   get: generate key from multiple sources, input can be multiple input args or a dict with options

## settings

-   `RATELIMIT_TESTCLIENT_FALLBACK`: in case instead of a client ip a testclient is detected map to the fallback. Set to "invalid" to fail. Default ::1
-   `RATELIMIT_GROUP_HASH`: hash function which is used for the group hash (default: md5)
-   `RATELIMIT_KEY_HASH`: hash function which is used as default for the key hash, can be overridden with hash_algo (default: md5)
-   `RATELIMIT_ENABLED` disable ratelimit (e.g. for tests) (default: enabled)
-   `RATELIMIT_ENABLE` deprecated old name of RATELIMIT_ENABLED
-   `RATELIMIT_KEY_PREFIX`: internal prefix for the hash keys (so you don't have to create a new cache). Defaults to "frl:".
-   `RATELIMIT_DEFAULT_CACHE`: default cache to use, defaults to "default" and can be overridden by cache parameter
-   `RATELIMIT_TRUSTED_PROXIES`: "all" for allowing all ip addresses to provide forward informations, or an iterable with proxy ips (will be transformed to a set). Note there is a special ip: "unix" for unix sockets. Default: ["unix"]
    Used headers are: `Forwarded`, `X-Forwarded-For`

## Update Notes:


in version 8.0.0: rate is the 4th argument of a key function, I need it for django-fast-iprestrict

in version 7.3.0: rate is now optional (when having an appropiate key (function))

in version 7.2.0: `RATELIMIT_ENABLE` is renamed to `RATELIMIT_ENABLED`, the old setting is still available, note: in tests where this settings are changed dynamically you may have to import \_get_RATELIMIT_ENABLED and clear the cache, in most cases this isn't neccessary

in version 7.0.0 method, group and key functions take an additional parameter: action

in version 6.0.0 some small new restrictions are introduced for key functions as string

in version 5.0.0 the package was renamed to django_fast_ratelimit for having an unique namespace. Reason, we have now a companion library: django-fast-iprestrict
Sorry for the big breaking change.

in version 4.0.0 most parameters were made keyword only (helps finding bugs).

in version 3.0.0 the name parameter of (a)decorate_object was changed to ratelimit

in version 2.0.0 the parameter `raise_on_limit` was removed and replaced by check(block=True)

in version 1.0.0 the parameter `include_reset` was removed

in version 1.2.0 reset_epoch calls return the counter before reset instead of the count after

## TODO:

-   document and test "get" inbuild method
