
from django.http import HttpResponse
from django.test import TestCase, RequestFactory
from django.views.generic import View
from django.utils.decorators import method_decorator

import ratelimit


def func_beautyname(request):
    return HttpResponse()


@method_decorator(ratelimit.decorate(
    rate="1/s", key=b"34d<", group="here_required"
), name="dispatch")
class BogoView(View):

    def get(self, request, *args, **kwargs):
        return HttpResponse()


class DecoratorTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

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

    def test_view(self):
        r = self.factory.get("/home")
        BogoView.as_view()(r)
        self.assertEquals(
            r.ratelimit["group"],
            "here_required"
        )
