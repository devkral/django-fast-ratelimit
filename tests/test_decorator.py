import time

from django.http import HttpResponse
from django.test import TestCase, RequestFactory
from django.views.generic import View
from django.utils.decorators import method_decorator

import ratelimit


def func_beautyname(request):
    return HttpResponse()


@method_decorator(ratelimit.decorate(rate="1/s", key=b"abc2"), name="dispatch")
class BogoView(View):
    pass


class DecoratorTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        if time.monotonic() % 1 > 0.8:
            time.sleep(0.3)

    def test_basic(self):
        func = ratelimit.decorate(
            rate="2/s", key="ip", block=True
        )(func_beautyname)
        func = ratelimit.decorate(
            rate="1/s", key="ip"
        )(func)
        r = self.factory.get("/home")
        func(r)
        self.assertEquals(
            r.ratelimit["group"],
            "tests.test_decorator.func_beautyname"
        )
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r = self.factory.get("/home")
            func(r)
