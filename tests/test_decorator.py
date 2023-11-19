import time
import unittest

from django import VERSION
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils.decorators import method_decorator
from django.views.generic import View

import ratelimit


def func_beautyname(request):
    return HttpResponse()


async def afunc_beautyname(request):
    return HttpResponse()


@method_decorator(
    ratelimit.decorate(rate="1/2s", key=b"34d<", group="here_required1"),
    name="dispatch",
)
class BogoView(View):
    def get(self, request, *args, **kwargs):
        return HttpResponse()


@method_decorator(
    ratelimit.decorate(rate="1/s", key=b"34d<", group="here_required2"),
    name="get",
)
class AsyncBogoView(View):
    async def get(self, request, *args, **kwargs):
        return HttpResponse()


@method_decorator(
    ratelimit.decorate(rate="1/s", key=b"34d<", wait=True, group="here_required3"),
    name="get",
)
class AsyncBogoWaitView(View):
    async def get(self, request, *args, **kwargs):
        return HttpResponse()


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


class AsyncO2gView(View):
    async def get(self, request, *args, **kwargs):
        request.ratelimit2 = await ratelimit.aget_ratelimit(
            group=ratelimit.o2g(self.get),
            rate="1/s",
            key=b"o2gtest",
            action=ratelimit.Action.INCREASE,
        )
        if request.ratelimit2.request_limit > 0:
            return HttpResponse(status=400)
        return HttpResponse()


class DecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_basic(self):
        func = ratelimit.decorate(rate="1/2s", key="ip", block=True)(func_beautyname)
        r = self.factory.get("/home")
        func(r)
        self.assertEquals(r.ratelimit.group, "tests.test_decorator.func_beautyname")
        self.assertTrue(r.ratelimit.can_reset)
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r2 = self.factory.get("/home")
            func(r2)
        r.ratelimit.reset()
        r = self.factory.get("/home")
        func(r)

    def test_block_without_decorate(self):
        func = ratelimit.decorate(
            rate="1/2s",
            key="ip",
            block=True,
            decorate_name=None,
            group="test_block_without_decorate",
        )(func_beautyname)
        r = self.factory.get("/home")
        func(r)
        self.assertFalse(hasattr(r, "ratelimit"))
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r2 = self.factory.get("/home")
            func(r2)

    def test_disabled(self):
        func = ratelimit.decorate(rate="0/2s", key="ip")(func_beautyname)

        r = self.factory.get("/home")
        with self.assertRaises(ratelimit.Disabled):
            func(r)
        self.assertTrue(hasattr(r, "ratelimit"))

        func = ratelimit.decorate(rate=(0, 1), key="ip")(func_beautyname)

        with self.assertRaises(ratelimit.Disabled):
            r = self.factory.get("/home")
            func(r)

    def test_view(self):
        r = self.factory.get("/home")
        BogoView.as_view()(r)
        self.assertEquals(r.ratelimit.group, "here_required1")

    def test_o2goview(self):
        r = self.factory.get("/home")
        v = O2gView.as_view()
        v(r)
        self.assertEquals(
            r.ratelimit2.group,
            "%s.%s" % (O2gView.get.__module__, O2gView.get.__qualname__),
        )
        self.assertTrue(r.ratelimit2.can_reset)
        r = self.factory.get("/home")
        resp = v(r)
        self.assertEquals(resp.status_code, 400)


@unittest.skipIf(VERSION[:2] < (4, 0), "unsuported")
class AsyncDecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    async def test_basic(self):
        func = ratelimit.decorate(rate="1/2s", key="ip", block=True)(afunc_beautyname)
        r = self.factory.get("/home")
        await func(r)
        self.assertEquals(r.ratelimit.group, "tests.test_decorator.afunc_beautyname")
        self.assertTrue(r.ratelimit.can_reset)
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
        self.assertEquals(r1.ratelimit.group, "here_required2")

    async def test_waitview(self):
        r1 = self.factory.get("/home")
        old = time.time()
        v = AsyncBogoWaitView.as_view()
        asyncresult = v(r1)
        self.assertFalse(hasattr(r1, "ratelimit"))
        await asyncresult
        new = time.time()
        self.assertGreater(new - old, 1)

        self.assertEquals(r1.ratelimit.group, "here_required3")

    async def test_o2goview(self):
        r = self.factory.get("/home")
        v = AsyncO2gView.as_view()
        await v(r)
        self.assertEquals(
            r.ratelimit2.group,
            "%s.%s" % (AsyncO2gView.get.__module__, AsyncO2gView.get.__qualname__),
        )
        self.assertTrue(r.ratelimit2.can_reset)
        r = self.factory.get("/home")
        resp = await v(r)
        self.assertEquals(resp.status_code, 400)
