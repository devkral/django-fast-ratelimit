from faker import Faker

from django.test import (
    TestCase,
    RequestFactory,
    override_settings,
)

from ratelimit.misc import get_ip, get_RATELIMIT_TRUSTED_PROXY

faker = Faker()


class IpTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @classmethod
    def tearDownClass(cls):
        get_RATELIMIT_TRUSTED_PROXY.cache_clear()

    def test_nonproxy(self):
        rogue_address_forwarded = 'for="[{}]:42";by={},for="[{}]"'.format(
            faker.ipv6(), faker.ipv4(), faker.ipv6()
        )
        rogue_address_x_forwarded_for = '"[{}]:42",'.format(faker.ipv6())
        for addr in [faker.ipv4(), faker.ipv6()]:
            with self.subTest(addr=addr):
                request = self.factory.get(
                    "/customer/details",
                    REMOTE_ADDR=addr,
                    HTTP_FORWARDED=rogue_address_forwarded,
                    HTTP_X_FORWARDED_FOR=rogue_address_x_forwarded_for,
                )
                self.assertEqual(addr, get_ip(request))

    def _proxy_helper(self, remote_addr):
        rogue_address_x_forwarded_for = '"[{}]:42",'.format(faker.ipv6())
        for count, addr in enumerate([faker.ipv4(), faker.ipv6()]):
            with self.subTest("forwarded", addr=addr):
                if count == 1:
                    addr2 = f"[{addr}]"
                    address_forwarded = 'for="{}:42";by={},for="[{}]"'.format(
                        addr2, faker.ipv4(), faker.ipv6()
                    )
                else:
                    addr2 = addr
                    address_forwarded = 'for={}:42;by={},for="[{}]"'.format(
                        addr2, faker.ipv4(), faker.ipv6()
                    )
                request = self.factory.get(
                    "/customer/details",
                    REMOTE_ADDR=remote_addr,
                    HTTP_FORWARDED=address_forwarded,
                    HTTP_X_FORWARDED_FOR=rogue_address_x_forwarded_for,
                )
                self.assertEqual(addr, get_ip(request))
            with self.subTest("forwarded2", addr=addr):
                if count == 1:
                    addr2 = f"[{addr}]"
                    address_forwarded = 'for="{}";by={},for="[{}]"'.format(
                        addr2, faker.ipv4(), faker.ipv6()
                    )
                else:
                    addr2 = addr
                    address_forwarded = 'for={};by={},for="[{}]"'.format(
                        addr2, faker.ipv4(), faker.ipv6()
                    )
                request = self.factory.get(
                    "/customer/details",
                    REMOTE_ADDR=remote_addr,
                    HTTP_FORWARDED=address_forwarded,
                    HTTP_X_FORWARDED_FOR=rogue_address_x_forwarded_for,
                )
                self.assertEqual(addr, get_ip(request))

            with self.subTest("x-forwarded-for", addr=addr):
                if count == 1:
                    addr2 = f"[{addr}]"
                    address_x_forwarded_for = '"{}:42","[{}]"'.format(
                        addr2, faker.ipv6()
                    )
                else:
                    addr2 = addr
                    address_x_forwarded_for = '{}:42,"[{}]"'.format(
                        addr2, faker.ipv6()
                    )
                request = self.factory.get(
                    "/customer/details",
                    REMOTE_ADDR=remote_addr,
                    HTTP_X_FORWARDED_FOR=address_x_forwarded_for,
                )
                self.assertEqual(addr, get_ip(request))
            with self.subTest("x-forwarded-for2", addr=addr):
                if count == 1:
                    addr2 = f"[{addr}]"
                    address_x_forwarded_for = '"{}","[{}]"'.format(
                        addr2, faker.ipv6()
                    )
                else:
                    addr2 = addr
                    address_x_forwarded_for = '{},"[{}]"'.format(
                        addr2, faker.ipv6()
                    )
                request = self.factory.get(
                    "/customer/details",
                    REMOTE_ADDR=remote_addr,
                    HTTP_X_FORWARDED_FOR=address_x_forwarded_for,
                )
                self.assertEqual(addr, get_ip(request))

    def test_unixproxy(self):
        self._proxy_helper("")

    def test_proxy(self):
        proxy = faker.ipv4()
        get_RATELIMIT_TRUSTED_PROXY.cache_clear()
        with override_settings(RATELIMIT_TRUSTED_PROXIES=[proxy]):
            self._proxy_helper(proxy)
        get_RATELIMIT_TRUSTED_PROXY.cache_clear()
        with override_settings(RATELIMIT_TRUSTED_PROXIES="all"):
            self._proxy_helper(proxy)
