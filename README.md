# django-fast-ratelimit


Django-fast-ratelimit provides a secure and fast ratelimit facility based on the django caching framework.


## Installation

```` bash
pip install django-fast-ratelimit

````

Note: pip >= 19 is required, I use the novel pyproject.toml method

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

````




## TODO

* more documentation
