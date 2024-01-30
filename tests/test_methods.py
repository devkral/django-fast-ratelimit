import unittest

from django import VERSION
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

import django_fast_ratelimit as ratelimit


class SyncTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user_normal = User.objects.create_user(username="normal", is_staff=False)
        self.user_staff = User.objects.create_user(username="staff", is_staff=True)
        self.user_admin = User.objects.create_user(username="admin", is_superuser=True)

    def test_static(self):
        request = self.factory.get("/customer/details")
        r = ratelimit.get_ratelimit(
            group="test_methods_static",
            rate="1/s",
            key="static",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details")
        r = ratelimit.get_ratelimit(
            group="test_methods_static",
            rate="1/s",
            key="static",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        request = self.factory.get("/customer/details")
        r = ratelimit.get_ratelimit(
            group="test_methods_static",
            rate="1/s",
            key="static:static1",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

        class f:
            def __str__(self):
                return "ll"

        for arg in [b"fooa", f(), 1382]:
            ratelimit.get_ratelimit(
                group="test_methods_static",
                rate="1/s",
                key=("static", arg),
                request=request,
                action=ratelimit.Action.INCREASE,
            )

    def test_ip(self):
        request = self.factory.get("/customer/details")
        r = ratelimit.get_ratelimit(
            group="test_methods_ip",
            rate="1/s",
            key="ip:32/128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details")
        r = ratelimit.get_ratelimit(
            group="test_methods_ip",
            rate="1/s",
            key="ip:128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.1.1")
        r = ratelimit.get_ratelimit(
            group="test_methods_ip",
            rate="1/s",
            key="ip:128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

    def test_user(self):
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        r = ratelimit.get_ratelimit(
            group="test_methods_user",
            rate="1/s",
            key="user",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.2")
        r = ratelimit.get_ratelimit(
            group="test_methods_user",
            rate="1/s",
            key="user",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = ratelimit.get_ratelimit(
            group="test_methods_user",
            rate="1/s",
            key="user",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.2")
        request.user = self.user_normal
        r = ratelimit.get_ratelimit(
            group="test_methods_user",
            rate="1/s",
            key="user",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)

    def test_user_or_ip(self):
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        r = ratelimit.get_ratelimit(
            group="test_methods_user_or_ip",
            rate="1/s",
            key="user_or_ip",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        r = ratelimit.get_ratelimit(
            group="test_methods_user_or_ip",
            rate="1/s",
            key="user_or_ip:128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = ratelimit.get_ratelimit(
            group="test_methods_user_or_ip",
            rate="1/s",
            key="user_or_ip:32/128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = ratelimit.get_ratelimit(
            group="test_methods_user_or_ip",
            rate="1/s",
            key="user_or_ip",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)

    def test_user_and_ip(self):
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        r = ratelimit.get_ratelimit(
            group="test_methods_user_and_ip",
            rate="1/s",
            key="user_and_ip",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.2")
        r = ratelimit.get_ratelimit(
            group="test_methods_user_and_ip",
            rate="1/s",
            key="user_and_ip:128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = ratelimit.get_ratelimit(
            group="test_methods_user_and_ip",
            rate="1/s",
            key="user_and_ip:32/128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.2")
        request.user = self.user_normal
        r = ratelimit.get_ratelimit(
            group="test_methods_user_and_ip",
            rate="1/s",
            key="user_and_ip",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

    def test_ip_exempt_user(self):
        for i in range(2):
            request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
            request.user = self.user_normal
            r = ratelimit.get_ratelimit(
                group="test_methods_ip_exempt_user",
                rate="1/s",
                key="ip_exempt_user",
                request=request,
                action=ratelimit.Action.INCREASE,
            )
            self.assertEqual(r.request_limit, 0)

        for i in range(2):
            request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
            r = ratelimit.get_ratelimit(
                group="test_methods_ip_exempt_user",
                rate="1/s",
                key="ip_exempt_user",
                request=request,
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)

    def test_ip_exempt_privileged(self):
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = ratelimit.get_ratelimit(
            group="test_methods_ip_exempt_privileged",
            rate="1/s",
            key="ip_exempt_privileged",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = ratelimit.get_ratelimit(
            group="test_methods_ip_exempt_privileged",
            rate="1/s",
            key="ip_exempt_privileged",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        for user in [self.user_staff, self.user_admin]:
            request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
            request.user = user
            r = ratelimit.get_ratelimit(
                group="test_methods_ip_exempt_privileged",
                rate="1/s",
                key="ip_exempt_privileged",
                request=request,
                action=ratelimit.Action.INCREASE,
            )
            self.assertEqual(r.request_limit, 0)

    def test_ip_exempt_superuser(self):
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = ratelimit.get_ratelimit(
            group="test_methods_ip_exempt_superuser",
            rate="1/s",
            key="ip_exempt_superuser",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_staff
        r = ratelimit.get_ratelimit(
            group="test_methods_ip_exempt_superuser",
            rate="1/s",
            key="ip_exempt_superuser",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_admin
        r = ratelimit.get_ratelimit(
            group="test_methods_ip_exempt_superuser",
            rate="1/s",
            key="ip_exempt_superuser",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

    def test_reset_exemption(self):
        for keyfn in ["ip_exempt_user", "ip_exempt_privileged"]:
            for action in [ratelimit.Action.RESET, ratelimit.Action.RESET_EPOCH]:
                with self.subTest("%(key)s.%(action)s", key=keyfn, action=action.name):
                    for i in range(2):
                        request = self.factory.get(
                            "/customer/details", REMOTE_ADDR="127.0.0.1"
                        )
                        ratelimit.get_ratelimit(
                            group=f"test_methods_{keyfn}_{action.name}",
                            rate="1/s",
                            key=keyfn,
                            request=request,
                            action=ratelimit.Action.INCREASE,
                        )

                    request = self.factory.get(
                        "/customer/details", REMOTE_ADDR="127.0.0.1"
                    )
                    request.user = self.user_admin
                    r = ratelimit.get_ratelimit(
                        group=f"test_methods_{keyfn}_{action.name}",
                        rate="1/s",
                        key=keyfn,
                        request=request,
                        action=action,
                    )
                    request = self.factory.get(
                        "/customer/details", REMOTE_ADDR="127.0.0.1"
                    )
                    r = ratelimit.get_ratelimit(
                        group=f"test_methods_{keyfn}_{action.name}",
                        rate="1/s",
                        key=keyfn,
                        request=request,
                        action=ratelimit.Action.PEEK,
                    )
                    # would reset to start of request, request ha blank epoch
                    if action == ratelimit.Action.RESET_EPOCH:
                        self.assertEqual(r.request_limit, 1)
                    else:
                        self.assertEqual(r.request_limit, 0)

    def test_get(self):
        pass


@unittest.skipIf(VERSION[:2] < (4, 0), "unsuported")
class AsyncTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.test import AsyncRequestFactory

        factory = AsyncRequestFactory()
        request = factory.get("/customer/details", REMOTE_ADDR="127.0.1.1")
        if request.META["REMOTE_ADDR"] != "127.0.1.1":
            print(
                f"\nDjango ({VERSION}) "
                "AsyncRequestFactory doesn't pass REMOTE_ADDR, fallback to RequestFactory"
            )
            cls.factoryClass = RequestFactory
        else:
            cls.factoryClass = AsyncRequestFactory

    def setUp(self):
        self.factory = self.factoryClass()
        self.user_normal = User.objects.create_user(username="normal", is_staff=False)
        self.user_staff = User.objects.create_user(username="staff", is_staff=True)
        self.user_admin = User.objects.create_user(username="admin", is_superuser=True)

    async def test_ip(self):
        request = self.factory.get("/customer/details")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_ip",
            rate="1/s",
            key="ip:32/128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_ip",
            rate="1/s",
            key="ip:128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.1.1")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_ip",
            rate="1/s",
            key="ip:128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

    async def test_user(self):
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user",
            rate="1/s",
            key="user",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.2")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user",
            rate="1/s",
            key="user",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user",
            rate="1/s",
            key="user",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.2")
        request.user = self.user_normal
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user",
            rate="1/s",
            key="user",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)

    async def test_user_or_ip(self):
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user_or_ip",
            rate="1/s",
            key="user_or_ip",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user_or_ip",
            rate="1/s",
            key="user_or_ip:128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user_or_ip",
            rate="1/s",
            key="user_or_ip:32/128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user_or_ip",
            rate="1/s",
            key="user_or_ip",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)

    async def test_user_and_ip(self):
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user_and_ip",
            rate="1/s",
            key="user_and_ip",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.2")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user_and_ip",
            rate="1/s",
            key="user_and_ip:128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user_and_ip",
            rate="1/s",
            key="user_and_ip:32/128",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.2")
        request.user = self.user_normal
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_user_and_ip",
            rate="1/s",
            key="user_and_ip",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

    async def test_ip_exempt_user(self):
        for i in range(2):
            request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
            request.user = self.user_normal
            r = await ratelimit.aget_ratelimit(
                group="test_methodsa_ip_exempt_user",
                rate="1/s",
                key="ip_exempt_user",
                request=request,
                action=ratelimit.Action.INCREASE,
            )
            self.assertEqual(r.request_limit, 0)

        for i in range(2):
            request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
            r = await ratelimit.aget_ratelimit(
                group="test_methodsa_ip_exempt_user",
                rate="1/s",
                key="ip_exempt_user",
                request=request,
                action=ratelimit.Action.INCREASE,
            )
        self.assertEqual(r.request_limit, 1)

        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_ip_exempt_user",
            rate="1/s",
            key="ip_exempt_user",
            request=request,
            action=ratelimit.Action.RESET,
        )
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_ip_exempt_user",
            rate="1/s",
            key="ip_exempt_user",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)

    async def test_ip_exempt_privileged(self):
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_ip_exempt_privileged",
            rate="1/s",
            key="ip_exempt_privileged",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 0)
        request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
        request.user = self.user_normal
        r = await ratelimit.aget_ratelimit(
            group="test_methodsa_ip_exempt_privileged",
            rate="1/s",
            key="ip_exempt_privileged",
            request=request,
            action=ratelimit.Action.INCREASE,
        )
        self.assertEqual(r.request_limit, 1)
        for user in [self.user_staff, self.user_admin]:
            request = self.factory.get("/customer/details", REMOTE_ADDR="127.0.0.1")
            request.user = user
            r = await ratelimit.aget_ratelimit(
                group="test_methodsa_ip_exempt_privileged",
                rate="1/s",
                key="ip_exempt_privileged",
                request=request,
                action=ratelimit.Action.INCREASE,
            )
            self.assertEqual(r.request_limit, 0)
