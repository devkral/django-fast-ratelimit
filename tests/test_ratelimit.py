import hashlib
import time
import types

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings

import ratelimit
from ratelimit._core import (
    _get_cache_key,
    _get_group_hash,
    _retrieve_key_func,
    parse_rate,
)


class ConstructionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

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
        _retrieve_key_func("ip")(self.factory.get("/home"), "foo")

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
            parse_rate(None)
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
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 1)

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
        r.reset()
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
        r.reset(epoch)
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
        r.reset(epoch)
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
                methods=["POST"],
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
                            group="test_backends",
                            rate="1/s",
                            key=b"implicittest",
                        )
                        self.assertEqual(r.request_limit, 0)

                    for i in range(0, 2):
                        r = ratelimit.get_ratelimit(
                            group="test_backends",
                            rate="1/s",
                            key=b"implicittest",
                            action=ratelimit.Action.INCREASE,
                        )
                    self.assertEqual(r.request_limit, 1)
                    r = ratelimit.get_ratelimit(
                        group="test_backends",
                        rate="1/s",
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
                            group="test_backends",
                            rate="1/s",
                            key=b"explicittest",
                            cache=cache,
                        )
                        self.assertEqual(r.request_limit, 0)

                    for i in range(0, 2):
                        r = ratelimit.get_ratelimit(
                            group="test_backends",
                            rate="1/s",
                            key=b"explicittest",
                            action=ratelimit.Action.INCREASE,
                            cache=cache,
                        )
                    self.assertEqual(r.request_limit, 1)
                    r = ratelimit.get_ratelimit(
                        group="test_backends",
                        rate="1/s",
                        key=b"explicittest",
                        action=ratelimit.Action.INCREASE,
                        cache=cache,
                    )
                    self.assertEqual(r.request_limit, 1)
            _get_group_hash.cache_clear()


class AsyncTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

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
        await r.areset(epoch)
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
        await r.areset(epoch)
        r = await ratelimit.aget_ratelimit(
            group="atest_reset_epoch_obj_fn",
            rate="2/m",
            key=b"abc2",
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        self.assertEqual(r.count, 2)
