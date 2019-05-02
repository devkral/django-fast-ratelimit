
import hashlib
import types
import time

from django.test import (
    TestCase, TransactionTestCase, RequestFactory, override_settings
)

import ratelimit
from ratelimit._core import (
    _retrieve_key_func, _get_cache_key, _parse_rate, _get_group_hash
)


class ConstructionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_key_length_limits(self):
        _get_group_hash.cache_clear()
        for ha in ["md5", "sha256", "sha512"]:
            with override_settings(RATELIMIT_GROUP_HASH=ha):
                h = hashlib.new(ha)
                k = _get_cache_key("foo"*255, h, "rfl:")
                self.assertLess(len(k), 256, "%s: %s" % (ha, len(k)))
            _get_group_hash.cache_clear()

    def test_keyfunc_retrieval(self):
        self.assertIsInstance(_retrieve_key_func("ip"), types.FunctionType)
        _retrieve_key_func("ip")(self.factory.get("/home"), "foo")

    def test_parse_rate(self):
        for rate in [
            ("1/4", (1, 4)),
            ("1/1s", (1, 1)),
            ("4/m", (4, 60)),
            ("6/h", (6, 3600)),
            ("7/d", (7, 3600*24)),
            ("1/w", (1, 3600*24*7)),
            ((1, 6), (1, 6)),
            ([3, 7], (3, 7))
        ]:
            r = _parse_rate(rate[0])
            self.assertEqual(len(r), 2)
            self.assertEqual(r, rate[1])
        with self.assertRaisesRegex(ValueError, "invalid rate"):
            _parse_rate("1")


class RatelimitTests(TransactionTestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def test_basic(self):
        r = None
        for i in range(0, 4):
            r = ratelimit.get_ratelimit(
                group="foo", rate="1/s", key=b"abc"
            )
            self.assertEqual(r["request_limit"], 0)

        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="foo", rate="1/s", key=b"abc2", inc=True
            )
        self.assertEqual(r["request_limit"], 1)
        r = ratelimit.get_ratelimit(
            group="foo", rate="1/s", key=b"abc2", inc=True
        )
        self.assertEqual(r["request_limit"], 1)
        time.sleep(2)
        r = ratelimit.get_ratelimit(
            group="foo", rate="1/s", key=b"abc2", inc=True
        )
        self.assertEqual(r["request_limit"], 0)

    def test_request(self):
        r = None
        request = self.factory.get('/customer/details')
        for i in range(0, 4):
            r = ratelimit.get_ratelimit(
                group="foo", rate="1/s", key="ip", request=request
            )
            self.assertEqual(r["request_limit"], 0)

        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="foo", rate="1/s", key="ip:32/64", inc=True,
                request=request
            )
        self.assertEqual(r["request_limit"], 1)
        r = ratelimit.get_ratelimit(
            group="foo", rate="1/s", key="ip", inc=True, request=request
        )
        self.assertEqual(r["request_limit"], 1)

    def test_request_post_get_filter(self):
        r = None
        request = self.factory.get('/customer/details')
        for i in range(0, 4):
            r = ratelimit.get_ratelimit(
                group="abasd", rate="1/s", key="ip", request=request, inc=True,
                methods=["POST"]
            )
            self.assertEqual(r["request_limit"], 0)

        for i in range(0, 2):
            r = ratelimit.get_ratelimit(
                group="abasd", rate="1/s", key="ip:32/64", inc=True,
                request=request, methods=["GET"]
            )
        self.assertEqual(r["request_limit"], 1)
        r = ratelimit.get_ratelimit(
            group="abasd", rate="1/s", key="ip", inc=True, request=request,
            methods=["GET"]
        )
        self.assertEqual(r["request_limit"], 1)

    def test_inverted(self):
        request = self.factory.get('/customer/details')
        r = ratelimit.get_ratelimit(
            group="zafaiusl", rate="1/s", key="ip:32/64", inc=True,
            request=request, methods=ratelimit.invertedset(["GET"])
        )
        self.assertEqual(r["count"], 0)

    def test_backends_impicit(self):
        for ha in ["md5", "sha256", "sha512"]:
            for cache in ["default", "db"]:
                with override_settings(
                    RATELIMIT_DEFAULT_CACHE=cache, RATELIMIT_GROUP_HASH=ha,
                    RATELIMIT_KEY_HASH=ha
                ):
                    r = None
                    for i in range(0, 4):
                        r = ratelimit.get_ratelimit(
                            group="foo", rate="1/s", key=b"implicittest"
                        )
                        self.assertEqual(r["request_limit"], 0)

                    for i in range(0, 2):
                        r = ratelimit.get_ratelimit(
                            group="foo", rate="1/s", key=b"implicittest",
                            inc=True
                        )
                    self.assertEqual(r["request_limit"], 1)
                    r = ratelimit.get_ratelimit(
                        group="foo", rate="1/s", key=b"implicittest", inc=True
                    )
                    self.assertEqual(r["request_limit"], 1)
            _get_group_hash.cache_clear()

    def test_backends_explicit(self):
        for ha in ["md5", "sha256", "sha512"]:
            for cache in ["default", "db"]:
                with override_settings(
                    RATELIMIT_GROUP_HASH=ha, RATELIMIT_KEY_HASH=ha
                ):
                    r = None
                    for i in range(0, 4):
                        r = ratelimit.get_ratelimit(
                            group="foo", rate="1/s", key=b"explicittest",
                            cache=cache
                        )
                        self.assertEqual(r["request_limit"], 0)

                    for i in range(0, 2):
                        r = ratelimit.get_ratelimit(
                            group="foo", rate="1/s", key=b"explicittest",
                            inc=True, cache=cache
                        )
                    self.assertEqual(r["request_limit"], 1)
                    r = ratelimit.get_ratelimit(
                        group="foo", rate="1/s", key=b"explicittest", inc=True,
                        cache=cache
                    )
                    self.assertEqual(r["request_limit"], 1)
            _get_group_hash.cache_clear()
