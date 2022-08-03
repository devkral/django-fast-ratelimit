from django.http import HttpResponse
from django.test import TestCase, RequestFactory
from django.views.generic import View
from django.utils.decorators import method_decorator

import ratelimit


def func_beautyname(request):
    return HttpResponse()


@method_decorator(
    ratelimit.decorate(rate="1/s", key=b"34d<", group="here_required"),
    name="dispatch",
)
class BogoView(View):
    def get(self, request, *args, **kwargs):
        return HttpResponse()


class O2gView(View):
    def get(self, request, *args, **kwargs):
        request.ratelimit2 = ratelimit.get_ratelimit(
            group=ratelimit.o2g(self.get),
            rate="1/s",
            key=b"o2gtest",
            action=ratelimit.Action.INCREASE,
            include_reset=True,
        )
        if request.ratelimit2.request_limit > 0:
            return HttpResponse(status=400)
        return HttpResponse()


class DecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_basic(self):
        func = ratelimit.decorate(rate="2/2s", key="ip", block=True)(
            func_beautyname
        )
        func = ratelimit.decorate(rate="1/2s", key="ip")(func)
        r = self.factory.get("/home")
        func(r)
        self.assertEquals(
            r.ratelimit.group, "tests.test_decorator.func_beautyname"
        )
        self.assertTrue(callable(r.ratelimit.reset))
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r = self.factory.get("/home")
            func(r)
        r.ratelimit.reset()
        r = self.factory.get("/home")
        func(r)

    def test_view(self):
        r = self.factory.get("/home")
        BogoView.as_view()(r)
        self.assertEquals(r.ratelimit.group, "here_required")
        r = self.factory.get("/home")
        v = O2gView.as_view()
        v(r)
        self.assertEquals(
            r.ratelimit2.group,
            "%s.%s" % (O2gView.get.__module__, O2gView.get.__qualname__),
        )
        self.assertTrue(callable(r.ratelimit2.reset))
        r = self.factory.get("/home")
        resp = v(r)
        self.assertEquals(resp.status_code, 400)
