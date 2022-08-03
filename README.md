# django-fast-ratelimit


Django-fast-ratelimit provides a secure and fast ratelimit facility based on the django caching framework.
It uses a "Fixed window counter"-algorithm based on:
https://medium.com/figma-design/an-alternative-approach-to-rate-limiting-f8a06cf7c94c



## Installation

```` bash
pip install django-fast-ratelimit

````

Note: pip >= 19 is required

## usage


Decorator:

```` python
import ratelimit

@ratelimit.decorate(key="ip", rate="1/s")
def expensive_func(request):
    # how many ratelimits request limiting
    if request.ratelimit["request_limit"] > 0:
        # reschedule with end of rate epoch
        return request_waiting(request.ratelimit["end"])

````

blocking Decorator (raises RatelimitError):

```` python
import ratelimit

@ratelimit.decorate(key="ip", rate="1/s", block=True, methods=ratelimit.UNSAFE)
def expensive_func(request):
    # how many ratelimits request limiting
    if request.ratelimit["end"] > 0:

````



decorate View (requires group):

```` python
import ratelimit
from django.views.generic import View
from django.utils.decorators import method_decorator


@method_decorator(ratelimit.decorate(
  key="ip", rate="1/s", block=True, methods=ratelimit.SAFE, group="required"
), name="dispatch")
class FooView(View):
    ...

````

manual
```` python
import ratelimit


def func(request):
    ratelimit.get_ratelimit(key="ip", rate="1/s", request=request, group="123")
    # or only for GET
    ratelimit.get_ratelimit(
        key="ip", rate="1/s", request=request, group="123", methods="GET"
    )
    # also simple calls possible (note: key in bytes format)
    ratelimit.get_ratelimit(
        key=b"abc", rate="1/s", group="123"
    )
    # check constraints of rate
    r = ratelimit.parse_rate("1/s")  # returns tuple (amount, period)
    assert(r[1]==1)  #  assert period is 1 second
    # for simple naming use o2g (object to group)
    ratelimit.get_ratelimit(
        key=b"abc", rate=r, group=ratelimit.o2g(func)
    )

````

## parameters

### ratelimit.get_ratelimit:

* group: group name, can be callable (fun(request))
* methods: set of checked methods, can be callable (fun(request, group)), modes:
  * callable(request, group): allow dynamic
  * ratelimit.ALL (default): all methods are checked
  * \("HEAD", "GET"\): list of checked methods
  * ratelimit.invertedset(["HEAD", "GET"]): inverted set of checked methods. Here: every method is checked, except HEAD, GET
* request: ingoing request (optional if key supports it and methods=ratelimit.ALL (default))
* key: multiple modes possible:
    * bool: True: skip key (should only be used for baking), False: disable cache (like RATELIMIT_ENABLE=False)
    * int:  sidestep cache, value will be used for request_limit. 0 is for never blocking, >=1 blocks
    * str: "path.to.method:argument"
    * str: "inbuildmethod:argument" see methods for valid arguments
    * str: "inbuildmethod"  method which is ready to use for (request, group)
    * tuple,list: ["method", args...]: method (can be also inbuild) with arbitary arguments
    * bytes: static key (supports mode without request)
    * callable: check return of function (fun(request, group)), return must be string (converted to bytes), bytes, bool or int (see "key" for effects)
  * empty_to: convert empty keys (b"") to parameter. Must be bytes, bool or int (see "key" for effects) (default: keep b"")
  * cache: specify cache to use, defaults to RATELIMIT_DEFAULT_CACHE setting (default: "default")
  * hash_algo: name of hash algorithm for creating cache_key (defaults to RATELIMIT_KEY_HASH setting (default: "sha256"))
    Note: group is seperately hashed
  * hashctx: optimation parameter, read the code and only use if you know what you are doing. It basically circumvents the parameter hashing and only hashes the key. If the key parameter is True even the key is skipped
  * action {ratelimit.Action}:
    *  PEEK: only lookup
    *  INCREASE: count up and return result
    *  RESET: return former result and reset (default: {PEEK})
  * include_reset: add reset method to Ratelimit object if no cache bypass is in use

returns following dict

* count: how often in the window the ip whatever was calling
* limit: limit when it should block
* request_limit: >=1 should block or reject, 0: should accept
* end: when does the block end
* group: group name


### ratelimit.decorate:

All of ratelimit.get_ratelimit except request. group is here optional (except for decorations with method_decorator (no access to wrapped function)).
Also supports:
* block: should hard block with an RatelimitExceeded exception (subclass of PermissionDenied) or only annotate request with ratelimit

## helpers

* ratelimit.invertedset: inverts a collection, useful for http methods
* ratelimit.o2g: auto generate group names

## methods

See in methods which methods are available. Here some of them:
* ip: use ip address as key, argument: [netmask ipv4/]netmask ipv6
* user: authenticated user primary key or b""
* user_or_ip: use autenticated user primary key as key. If not autenticated fallback to ip, also with netmask argument
* user_and_ip: same like user_or_ip except that the ip matching also applies for authenticated users
* get: generate key from multiple sources, input can be multiple input args or a dict with options

## settings

* RATELIMIT_GROUP_HASH: hash function which is used for the group hash (default: md5)
* RATELIMIT_KEY_HASH: hash function which is used as default for the key hash, can be overridden with hash_algo (default: md5)
* RATELIMIT_ENABLE disable ratelimit (e.g. for tests) (default: enabled)
* RATELIMIT_KEY_PREFIX: internal prefix for the hash keys (so you don't have to create a new cache). Defaults to "frl:".
* RATELIMIT_DEFAULT_CACHE: default cache to use, defaults to "default" and can be overridden by cache parameter


## TODO

* more documentation
