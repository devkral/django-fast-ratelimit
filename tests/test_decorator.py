import time
import unittest

from django import VERSION
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils.decorators import method_decorator
from django.views.generic import View

import django_fast_ratelimit as ratelimit


def func_beautyname(request):
    return HttpResponse()


def func_beautyname2(request):
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

    def test_decorate_without_rate(self):
        def fn(request, group, action, rate):
            return 0

        func = ratelimit.decorate(key=fn)(func_beautyname)
        r = self.factory.get("/home")
        func(r)

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

    def test_methods_static(self):
        func = ratelimit.decorate(
            rate="1/2s",
            key="ip",
            methods="POST",
            group="test_methods_static",
            block=True,
        )(func_beautyname)
        for i in range(2):
            func(self.factory.get("/home"))
        func(self.factory.post("/home"))

        with self.assertRaises(ratelimit.RatelimitExceeded):
            func(self.factory.post("/home"))

        func = ratelimit.decorate(
            rate="1/2s",
            key="ip",
            methods={"PUT"},
            group="test_methods_static",
            block=True,
        )(func_beautyname)
        for i in range(2):
            func(self.factory.post("/home"))
        func(self.factory.put("/home"))
        with self.assertRaises(ratelimit.RatelimitExceeded):
            func(self.factory.put("/home"))

    def test_methods_fn(self):
        def methods(request, group, action):
            return "POST"

        func = ratelimit.decorate(
            rate="1/2s",
            key="ip",
            methods=methods,
            group="test_methods_fn",
            block=True,
        )(func_beautyname)
        for i in range(2):
            func(self.factory.get("/home"))
        func(self.factory.post("/home"))

        with self.assertRaises(ratelimit.RatelimitExceeded):
            func(self.factory.post("/home"))

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

    def test_force_async(self):
        with self.subTest("explicit force_async"):
            func = ratelimit.decorate(
                rate="2/2s", key="ip", group="force_async1", force_async=True
            )(func_beautyname)

            with self.assertRaises(AssertionError):
                r = self.factory.get("/home")
                func(r)

        with self.subTest("implicit force_async"):
            func = ratelimit.decorate(
                rate="2/2s", key="ip", group="force_async2", wait=True
            )(func_beautyname)
            with self.assertRaises(AssertionError):
                r = self.factory.get("/home")
                func(r)
        with self.subTest("disabled force_async"):
            func = ratelimit.decorate(
                rate="2/2s",
                key="ip",
                group="force_async3",
                wait=True,
                force_async=False,
            )(func_beautyname)

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

    async def test_decorate_without_rate(self):
        async def fn(request, group, action, rate):
            return 0

        func = ratelimit.decorate(key=fn)(afunc_beautyname)
        r = self.factory.get("/home")
        await func(r)

    async def test_basic(self):
        # sync
        func = ratelimit.decorate(rate="1/2s", key="ip", block=True)(func_beautyname2)
        r = self.factory.get("/home")
        await func(r)
        self.assertEquals(r.ratelimit.group, "tests.test_decorator.func_beautyname2")
        # as well as async
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

    async def test_methods_static(self):
        func = ratelimit.decorate(
            rate="1/2s",
            key="ip",
            methods="POST",
            group="test_amethods_static",
            block=True,
        )(afunc_beautyname)
        for i in range(2):
            await func(self.factory.get("/home"))
        await func(self.factory.post("/home"))
        with self.assertRaises(ratelimit.RatelimitExceeded):
            await func(self.factory.post("/home"))
        func = ratelimit.decorate(
            rate="1/2s",
            key="ip",
            methods={"PUT"},
            group="test_amethods_static",
            block=True,
        )(afunc_beautyname)
        for i in range(2):
            await func(self.factory.post("/home"))
        await func(self.factory.put("/home"))
        with self.assertRaises(ratelimit.RatelimitExceeded):
            await func(self.factory.put("/home"))

    async def test_methods_fn(self):
        async def methods(request, group, action):
            return "POST"

        func = ratelimit.decorate(
            rate="1/2s",
            key="ip",
            methods=methods,
            group="test_amethods_fn",
            block=True,
        )(afunc_beautyname)
        for i in range(2):
            await func(self.factory.get("/home"))
        await func(self.factory.post("/home"))

        with self.assertRaises(ratelimit.RatelimitExceeded):
            await func(self.factory.post("/home"))

    async def test_view(self):
        r1 = self.factory.get("/home")
        v = AsyncBogoView.as_view()
        await v(r1)
        self.assertEquals(r1.ratelimit.group, "here_required2")

    async def test_waitview(self):
        v = AsyncBogoWaitView.as_view()
        await v(self.factory.get("/home"))
        old = time.time()
        r1 = self.factory.get("/home")
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
