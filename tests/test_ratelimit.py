import hashlib
import time
import types
import unittest
from functools import partial, singledispatch

from django import VERSION
from django.contrib.auth.models import AnonymousUser
from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.dummy import DummyCache
from django.test import RequestFactory, TestCase, override_settings

import django_fast_ratelimit as ratelimit
from django_fast_ratelimit._core import (
    _get_cache_key,
    _get_group_hash,
    _get_RATELIMIT_ENABLED,
    _retrieve_key_func,
    parse_rate,
)


class AlternatingAdd(DummyCache):
    def __init__(self, host="foo", *args, **kwargs):
        super().__init__(host, {}, *args, **kwargs)
        self._random_counter = 0

    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        super().add(key, value, timeout=timeout, version=version)
        self._random_counter = (self._random_counter + 1) % 2
        return self._random_counter == 0


def _prefixed_function(request, group, action, rate):
    return b"foobar"


@singledispatch
def fake_key_function(request, group, action, rate, arg1="fake1", arg2=""):
    return "".join((arg1, arg2))


@fake_key_function.register(str)
def _(arg1: str, arg2: str = ""):
    return partial(fake_key_function, arg1=arg1, arg2=arg2)


class ConstructionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_action_compatibility(self):
        # will fail with plain Enum
        for value in ratelimit.Action.__members__.values():
            self.assertEqual(value, value.value)

    def test_key_length_limits(self):
        _get_group_hash.cache_clear()
        for ha in ["md5", "sha256", "sha512"]:
            with override_settings(RATELIMIT_GROUP_HASH=ha):
                h = hashlib.new(ha)
                k = _get_cache_key("foo" * 255, h, "rfl:")
                self.assertLess(len(k), 256, "%s: %s" % (ha, len(k)))
            _get_group_hash.cache_clear()

    def test_keyfunc_retrieval(self):
        self.assertIsInstance(_retrieve_key_func("ip"), types.FunctionType)
        _retrieve_key_func("ip")(
            self.factory.get("/home"), "foo", ratelimit.Action.PEEK, None
        )
        with self.assertRaises(ValueError):
            _retrieve_key_func("_ip")
        with self.assertRaises(ValueError):
            _retrieve_key_func(b"notvalidhere")
        with self.assertRaises(ValueError):
            _retrieve_key_func("tests.test_ratelimit._prefixed_function")

        self.assertIsInstance(
            _retrieve_key_func("tests.test_ratelimit.fake_key_function"),
            types.FunctionType,
        )
        self.assertEqual(
            _retrieve_key_func("tests.test_ratelimit.fake_key_function")(
                self.factory.get("/home"), "foo", ratelimit.Action.PEEK, None
            ),
            "fake1",
        )
        self.assertEqual(
            _retrieve_key_func("tests.test_ratelimit.fake_key_function:fake2")(
                self.factory.get("/home"), "foo", ratelimit.Action.PEEK, None
            ),
            "fake2",
        )

        self.assertEqual(
            _retrieve_key_func(("tests.test_ratelimit.fake_key_function", "fake", "2"))(
                self.factory.get("/home"), "foo", ratelimit.Action.PEEK, None
            ),
            "fake2",
        )

        self.assertEqual(
            _retrieve_key_func((fake_key_function, "fake", "2"))(
                self.factory.get("/home"), "foo", ratelimit.Action.PEEK, None
            ),
            "fake2",
        )

    def testparse_rate(self):
        for rate in [
            ("1/4", (1, 4)),
            ("1/1s", (1, 1)),
            ("4/m", (4, 60)),
            ("6/h", (6, 3600)),
            ("7/d", (7, 3600 * 24)),
            ("1/w", (1, 3600 * 24 * 7)),
            ((1, 6), (1, 6)),
            ([3, 7], (3, 7)),
            ("0/4", (0, 4)),
        ]:
            r = parse_rate(rate[0])
            self.assertEqual(len(r), 2)
            self.assertEqual(r, rate[1])
        with self.assertRaises(NotImplementedError):
            parse_rate(True)
        with self.assertRaisesRegex(ValueError, "invalid rate format"):
            parse_rate("1")
        with self.assertRaisesRegex(AssertionError, "invalid rate detected"):
            parse_rate("1/0s")
        with self.assertRaisesRegex(AssertionError, "invalid rate detected"):
            parse_rate([1, 0])
        with self.assertRaisesRegex(AssertionError, "invalid rate detected"):
            parse_rate([1, 1, 1])


class RatelimitTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_basic(self):
        r = None
        for i in range(0, 4):
            # just view, without retrieving
            r = ratelimit.get_ratelimit(group="test_basic", rate="1/s", key=b"abc")
            self.assertEqual(r.request_limit, 0)

        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_basic",
                rate="1/s",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r.check(block=True)

        self.assertEqual(r.count, 2)
        r = ratelimit.get_ratelimit(
            group="test_basic",
            rate="1/s",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        time.sleep(2)
        r = ratelimit.get_ratelimit(
            group="test_basic",
            rate="1/s",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

    def test_bad_rate_keyfn(self):
        def fn(request, group, action, rate):
            return b"klsds"

        with self.assertRaisesRegex(
            ratelimit.MissingRate,
            r"rate argument is missing or None and the key \(function\) doesn't sidestep cache",
        ):
            ratelimit.get_ratelimit(group="test_bad_rate_keyfn", key=fn)

    def test_no_rate_keyfn(self):
        def fn(request, group, action, rate):
            self.assertIs(rate, None)
            return False

        def fn2(request, group, action, rate):
            self.assertIs(rate, None)
            return 0

        def fn3(request, group, action, rate):
            self.assertIs(rate, None)
            return 1

        ratelimit.get_ratelimit(group="test_no_rate_keyfn", key=fn)
        ratelimit.get_ratelimit(group="test_no_rate_keyfn", key=fn2)
        ratelimit.get_ratelimit(group="test_no_rate_keyfn", key=fn3)
        ratelimit.get_ratelimit(group="test_no_rate_keyfn", key=1)

    def test_fallbacks(self):
        r = ratelimit.get_ratelimit(group="test_fallbacks", rate="1/10s", key=b"abc")
        r.cache.set(f"{r.cache_key}_expire", int(time.time()) - 2)
        ratelimit.get_ratelimit(group="test_fallbacks", rate="1/10s", key=b"abc")

    def test_fallbacks_cache(self):
        cache = AlternatingAdd()
        r = ratelimit.get_ratelimit(
            group="test_fallbacks",
            cache=cache,
            rate="1/10s",
            key=b"abc",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.count, 1)

    def test_disabled_ratelimit(self):
        with self.assertRaises(ratelimit.Disabled):
            ratelimit.get_ratelimit(
                group="test_disabled_ratelimit",
                rate="0/1s",
                key=b"abc",
                action=ratelimit.Action.INCREASE,
            )
        for t1, t2 in [(False, None), (None, False), (False, False)]:
            with override_settings(RATELIMIT_ENABLED=t1, RATELIMIT_ENABLE=t2):
                with self.subTest(t1=t1, t2=t2):
                    _get_RATELIMIT_ENABLED.cache_clear()
                    if t1 is None and t2 is not None:
                        with self.assertWarns(DeprecationWarning):
                            ratelimit.get_ratelimit(
                                group="test_disabled_ratelimit",
                                rate="0/1s",
                                key=b"abc",
                                action=ratelimit.Action.INCREASE,
                            )
                    else:
                        ratelimit.get_ratelimit(
                            group="test_disabled_ratelimit",
                            rate="0/1s",
                            key=b"abc",
                            action=ratelimit.Action.INCREASE,
                        )

    def test_function_arguments_no_request(self):
        def group_fn(request, action):
            self.assertIs(request, None)
            self.assertEqual(action, ratelimit.Action.INCREASE)
            return "test_arguments_no_request"

        def methods_fn(request, group, action):
            self.assertIs(request, None)
            self.assertEqual(group, "test_arguments_no_request")
            self.assertEqual(action, ratelimit.Action.INCREASE)
            return ratelimit.ALL

        def rate_fn(request, group, action):
            self.assertIs(request, None)
            self.assertEqual(group, "test_arguments_no_request")
            self.assertEqual(action, ratelimit.Action.INCREASE)
            return "1/2s"

        def _prefixed_bytes_key_fn(request, group, action, rate):
            self.assertIs(request, None)
            self.assertEqual(group, "test_arguments_no_request")
            self.assertEqual(action, ratelimit.Action.INCREASE)
            return b"foo"

        r = ratelimit.get_ratelimit(
            group=group_fn,
            rate=rate_fn,
            methods=methods_fn,
            key=_prefixed_bytes_key_fn,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

    def test_function_arguments_with_request(self):
        def group_fn(request, action):
            self.assertTrue(request)
            self.assertEqual(action, ratelimit.Action.INCREASE)
            return "test_arguments_with_request"

        def methods_fn(request, group, action):
            self.assertTrue(request)
            self.assertEqual(group, "test_arguments_with_request")
            self.assertEqual(action, ratelimit.Action.INCREASE)
            return ratelimit.SAFE

        def rate_fn(request, group, action):
            self.assertTrue(request)
            self.assertEqual(group, "test_arguments_with_request")
            self.assertEqual(action, ratelimit.Action.INCREASE)
            return "1/2s"

        def _prefixed_bytes_key_fn(request, group, action, rate):
            self.assertTrue(request)
            self.assertEqual(group, "test_arguments_with_request")
            self.assertEqual(action, ratelimit.Action.INCREASE)
            return b"foo"

        request = self.factory.get("/customer/details")
        r = ratelimit.get_ratelimit(
            group=group_fn,
            rate=rate_fn,
            methods=methods_fn,
            key=_prefixed_bytes_key_fn,
            action=ratelimit.Action.INCREASE,
            request=request,
        )
        self.assertEqual(r.request_limit, 0)

    def test_manual_decorate(self):
        class Foo:
            pass

        for i in range(0, 3):
            r = ratelimit.get_ratelimit(
                group="test_manual_decorate",
                rate="2/m",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)
        obj = Foo()
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r.decorate_object(obj, name=None, block=True)
        self.assertFalse(hasattr(obj, "ratelimit"))
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r.decorate_object(obj, name=None, block=False)
            r.decorate_object(obj, block=True)
        self.assertTrue(hasattr(obj, "ratelimit"))

    def test_manual_decorate_fn(self):
        @ratelimit.get_ratelimit(
            group="test_manual_decorate_fn",
            rate="2/m",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        ).decorate_object()
        def fn():
            pass

    def test_manual_decorate_fn2(self):
        r = ratelimit.get_ratelimit(
            group="test_manual_decorate_fn",
            rate="2/m",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )

        @r.decorate_object
        def fn():
            pass

    def test_reset(self):
        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_reset",
                rate="1/s",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 2)
        r = ratelimit.get_ratelimit(
            group="test_reset",
            rate="1/s",
            key=b"abc2",
            action=ratelimit.Action.RESET,
        )
        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 2)
        r = ratelimit.get_ratelimit(
            group="test_reset",
            rate="1/s",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 1)

    def test_reset_epoch(self):
        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_reset_epoch",
                rate="1/s",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 2)
        r = ratelimit.get_ratelimit(
            group="test_reset_epoch",
            rate="1/s",
            key=b"abc2",
            action=ratelimit.Action.RESET_EPOCH,
            epoch=1,
        )
        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 2)

    def test_reset_fn(self):
        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_reset_fn",
                rate="1/s",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 2)
        self.assertEqual(r.reset(), 2)
        r = ratelimit.get_ratelimit(
            group="test_reset_fn",
            rate="1/s",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 1)

    def test_reset_epoch_num_fn(self):
        epoch = 3
        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_reset_epoch_num_fn",
                rate="1/s",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 2)
        self.assertEqual(r.reset(epoch), -1)
        r = ratelimit.get_ratelimit(
            group="test_reset_epoch_num_fn",
            rate="1/s",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 0)

    def test_reset_epoch_obj_fn(self):
        class Foo:
            pass

        epoch = Foo()
        ratelimit.get_ratelimit(
            group="test_reset_epoch_obj_fn",
            rate="2/m",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_reset_epoch_obj_fn",
                rate="2/m",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
                epoch=epoch,
            )

        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 3)
        self.assertEqual(r.reset(epoch), 1)
        # should stay the same
        self.assertEqual(r.reset(epoch), 1)
        r = ratelimit.get_ratelimit(
            group="test_reset_epoch_obj_fn",
            rate="2/m",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 2)

    def test_window(self):
        # window should start with first INCREASE and end after period
        # (fixed window counter algorithm)
        r = None
        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_window",
                rate="2/4s",
                key=b"abc",
                action=ratelimit.Action.INCREASE,
            )
            self.assertEqual(r.request_limit, 0)
            time.sleep(1)
        r = ratelimit.get_ratelimit(
            group="test_window",
            rate="2/4s",
            key=b"abc",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        # window times out
        time.sleep(3)
        r = ratelimit.get_ratelimit(
            group="test_window",
            rate="2/4s",
            key=b"abc",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

    def test_block_empty(self):
        request = self.factory.get("/customer/details")
        request.user = AnonymousUser()
        r = ratelimit.get_ratelimit(
            group="test_block_empty",
            rate="1/s",
            key="user",
            request=request,
            empty_to=123,
        )
        self.assertEqual(r.request_limit, 123)

    def test_bypass_empty(self):
        r = None
        request = self.factory.get("/customer/details")
        request.user = AnonymousUser()
        for i in range(0, 4):
            r = ratelimit.get_ratelimit(
                group="test_bypass_empty",
                rate="1/s",
                key="user",
                request=request,
                empty_to=0,
            )
        self.assertEqual(r.request_limit, 0)

    def test_disabled(self):
        with self.assertRaises(ratelimit.Disabled):
            ratelimit.get_ratelimit(
                group="test_disabled1",
                rate="0/s",
                key="ip",
                request=self.factory.get("/home"),
            )
        with self.assertRaises(ratelimit.Disabled):
            ratelimit.get_ratelimit(
                group="test_disabled2",
                rate=(0, 4),
                key="ip",
                request=self.factory.get("/home"),
            )

    def test_request(self):
        r = None
        request = self.factory.get("/customer/details")
        for i in range(0, 4):
            # peek 4 times
            r = ratelimit.get_ratelimit(
                group="test_request", rate="1/s", key="ip", request=request
            )
            self.assertEqual(r.request_limit, 0)

        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_request",
                rate="1/s",
                key="ip:32/64",
                action=ratelimit.Action.INCREASE,
                request=request,
            )
        self.assertEqual(r.request_limit, 1)
        with self.assertRaises(ratelimit.RatelimitExceeded):
            r.decorate_object(request, block=True)
        r = ratelimit.get_ratelimit(
            group="test_request",
            rate="1/s",
            key="ip",
            action=ratelimit.Action.INCREASE,
            request=request,
        )
        self.assertEqual(r.request_limit, 1)

    def test_request_reset_epoch(self):
        r = None
        request = self.factory.get("/customer/details")
        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_request_reset_epoch",
                rate="2/m",
                key=b"abc2",
                request=request,
                action=ratelimit.Action.INCREASE,
            )
        request = self.factory.get("/customer/details")
        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_request_reset_epoch",
                rate="2/m",
                key=b"abc2",
                request=request,
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)
        r.reset(request)
        request = self.factory.get("/customer/details")
        r = ratelimit.get_ratelimit(
            group="test_request_reset_epoch",
            rate="2/m",
            key=b"abc2",
            action=ratelimit.Action.PEEK,
            request=request,
        )
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 2)

    def test_request_post_get_filter(self):
        r = None
        request = self.factory.get("/customer/details")
        for i in range(0, 4):
            r = ratelimit.get_ratelimit(
                group="test_request_post_get_filter",
                rate="1/s",
                key="ip",
                request=request,
                action=ratelimit.Action.INCREASE,
                methods=["POST"] if i % 2 else "POST",
            )
            self.assertEqual(r.request_limit, 0)

        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="test_request_post_get_filter",
                rate="1/s",
                key="ip:32/64",
                action=ratelimit.Action.INCREASE,
                request=request,
                methods=["GET"],
            )
        self.assertEqual(r.request_limit, 1)
        r = ratelimit.get_ratelimit(
            group="test_request_post_get_filter",
            rate="1/s",
            key="ip",
            action=ratelimit.Action.INCREASE,
            request=request,
            methods=["GET"],
        )
        self.assertEqual(r.request_limit, 1)

    def test_inverted(self):
        request = self.factory.get("/customer/details")
        r = ratelimit.get_ratelimit(
            group="test_inverted",
            rate="1/s",
            key="ip:32/64",
            action=ratelimit.Action.INCREASE,
            request=request,
            methods=ratelimit.invertedset(["GET"]),
        )
        self.assertEqual(r.count, 0)

    def test_backends_impicit(self):
        for ha in ["md5", "sha256", "sha512"]:
            for cache in ["default", "db"]:
                with override_settings(
                    RATELIMIT_DEFAULT_CACHE=cache,
                    RATELIMIT_GROUP_HASH=ha,
                    RATELIMIT_KEY_HASH=ha,
                ):
                    r = None
                    for i in range(0, 4):
                        r = ratelimit.get_ratelimit(
                            group="test_backends_implicit",
                            rate="1/30s",
                            key=b"implicittest",
                        )
                        self.assertEqual(r.request_limit, 0)

                    for i in range(0, 2):
                        r = ratelimit.get_ratelimit(
                            group="test_backends_implicit",
                            rate="1/30s",
                            key=b"implicittest",
                            action=ratelimit.Action.INCREASE,
                        )
                    self.assertEqual(r.request_limit, 1)
                    r = ratelimit.get_ratelimit(
                        group="test_backends_implicit",
                        rate="1/30s",
                        key=b"implicittest",
                        action=ratelimit.Action.INCREASE,
                    )
                    self.assertEqual(r.request_limit, 1)
            _get_group_hash.cache_clear()

    def test_backends_explicit(self):
        for ha in ["md5", "sha256", "sha512"]:
            for cache in ["default", "db"]:
                with override_settings(RATELIMIT_GROUP_HASH=ha, RATELIMIT_KEY_HASH=ha):
                    r = None
                    for i in range(0, 4):
                        r = ratelimit.get_ratelimit(
                            group="test_backends_explicit",
                            rate="1/30s",
                            key=b"explicittest",
                            cache=cache,
                        )
                        self.assertEqual(r.request_limit, 0)

                    for i in range(0, 2):
                        r = ratelimit.get_ratelimit(
                            group="test_backends_explicit",
                            rate="1/30s",
                            key=b"explicittest",
                            action=ratelimit.Action.INCREASE,
                            cache=cache,
                        )
                    self.assertEqual(r.request_limit, 1)
                    r = ratelimit.get_ratelimit(
                        group="test_backends_explicit",
                        rate="1/30s",
                        key=b"explicittest",
                        action=ratelimit.Action.INCREASE,
                        cache=cache,
                    )
                    self.assertEqual(r.request_limit, 1)
            _get_group_hash.cache_clear()


@unittest.skipIf(VERSION[:2] < (4, 0), "unsuported")
class AsyncTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    async def test_sync_in_async(self):
        from django.utils.asyncio import async_unsafe

        @ratelimit.protect_sync_only
        @async_unsafe
        def raise_on_async(request, group, action, rate):
            return group

        await ratelimit.aget_ratelimit(
            group="test_sync_in_async",
            rate="1/s",
            key=raise_on_async,
        )

    async def test_fallbacks_cache(self):
        cache = AlternatingAdd()
        r = await ratelimit.aget_ratelimit(
            group="test_fallbacks",
            cache=cache,
            rate="1/10s",
            key=b"abc",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.count, 1)

    async def test_reset_fn(self):
        for i in range(0, 2):
            r = await ratelimit.aget_ratelimit(
                group="atest_reset_fn",
                rate="1/s",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 2)
        await r.areset()
        r = await ratelimit.aget_ratelimit(
            group="atest_reset_fn",
            rate="1/s",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 1)

    async def test_reset_epoch_num_fn(self):
        epoch = 3
        for i in range(0, 2):
            r = await ratelimit.aget_ratelimit(
                group="atest_reset_epoch_num_fn",
                rate="1/s",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 2)
        self.assertEqual(await r.areset(epoch), -1)
        r = await ratelimit.aget_ratelimit(
            group="atest_reset_epoch_num_fn",
            rate="1/s",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 0)

    async def test_reset_epoch_obj_fn(self):
        class Foo:
            pass

        epoch = Foo()
        await ratelimit.aget_ratelimit(
            group="atest_reset_epoch_obj_fn",
            rate="2/m",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        for i in range(0, 2):
            r = await ratelimit.aget_ratelimit(
                group="atest_reset_epoch_obj_fn",
                rate="2/m",
                key=b"abc2",
                action=ratelimit.Action.INCREASE,
                epoch=epoch,
            )

        self.assertEqual(r.request_limit, 1)
        self.assertEqual(r.count, 3)
        self.assertEqual(r.count, 3)
        self.assertEqual(await r.areset(epoch), 1)
        self.assertEqual(await r.areset(epoch), 1)
        r = await ratelimit.aget_ratelimit(
            group="atest_reset_epoch_obj_fn",
            rate="2/m",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 2)
