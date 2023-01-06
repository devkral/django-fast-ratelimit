from django.http import HttpResponse
from django.test import TestCase, RequestFactory
from django.views.generic import View
from django.utils.decorators import method_decorator
from django import VERSION
import unittest

import ratelimit


def func_beautyname(request):
    return HttpResponse()


async def afunc_beautyname(request):
    return HttpResponse()


@method_decorator(
    ratelimit.decorate(rate="1/s", key=b"34d<", group="here_required"),
    name="dispatch",
)
class BogoView(View):
    def get(self, request, *args, **kwargs):
        return HttpResponse()


@method_decorator(
    ratelimit.decorate(rate="1/s", key=b"34d<", group="here_required"),
    name="dispatch",
)
class AsyncBogoView(View):
    async def get(self, request, *args, **kwargs):
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


class AsyncO2gView(View):
    async def get(self, request, *args, **kwargs):
        request.ratelimit2 = await ratelimit.aget_ratelimit(
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
        func = ratelimit.decorate(rate="1/2s", key="ip", block=True)(
            func_beautyname
        )
        r = self.factory.get("/home")
        func(r)
        self.assertEquals(
            r.ratelimit.group, "tests.test_decorator.func_beautyname"
        )
        self.assertTrue(callable(r.ratelimit.reset))
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r2 = self.factory.get("/home")
            func(r2)
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


@unittest.skipIf(VERSION[:2] < (4, 1), "unsuported")
class AsyncDecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    async def test_basic(self):
        func = ratelimit.decorate(rate="1/2s", key="ip", block=True)(
            afunc_beautyname
        )
        r = self.factory.get("/home")
        await func(r)
        self.assertEquals(
            r.ratelimit.group, "tests.test_decorator.afunc_beautyname"
        )
        self.assertTrue(callable(r.ratelimit.reset))
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r2 = self.factory.get("/home")
            await func(r2)
        r.ratelimit.reset()
        r = self.factory.get("/home")
        await func(r)

    async def test_view(self):
        r1 = self.factory.get("/home")
        v = AsyncBogoView.as_view()
        await v(r1)
        self.assertEquals(r1.ratelimit.group, "here_required")
        r2 = self.factory.get("/home")
        v = AsyncO2gView.as_view()
        await v(r2)
        self.assertEquals(
            r2.ratelimit2.group,
            "%s.%s"
            % (AsyncO2gView.get.__module__, AsyncO2gView.get.__qualname__),
        )
        self.assertTrue(callable(r2.ratelimit2.reset))
        r2 = self.factory.get("/home")
        resp = await v(r2)
        self.assertEquals(resp.status_code, 400)
