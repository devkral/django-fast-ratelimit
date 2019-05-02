__all__ = ["user_or_ip", "user_and_ip", "ip", "user", "get"]

import functools
import ipaddress
from django.http import HttpRequest


@functools.singledispatch
def user_or_ip(request, group):
    if request.user.is_authenticated:
        return str(request.user.pk)
    return ipaddress.ip_network(
        request.META['REMOTE_ADDR'], strict=False
    ).compressed


@user_or_ip.register(str)
def _(netmask):
    # ipv4, ipv6, default ipv6 (ipv4 is too fragmented)
    netmask = netmask.split("/", 1)
    # turn mask into difference:
    if len(netmask) == 1:
        netmask = (0, int(netmask[0]))
    return user_or_ip()


@user_or_ip.register(list)
@user_or_ip.register(tuple)
def _(netmask):
    netmask = (32 - int(netmask[0]), 128 - int(netmask[1]))
    assert(netmask[0] >= 0)
    assert(netmask[1] >= 0)
    if netmask == (32, 128):
        return user_or_ip.dispatch(HttpRequest)

    def _(request, group):
        if request.user.is_authenticated:
            return str(request.user.pk)
        ipnet = ipaddress.ip_network(
            request.META['REMOTE_ADDR'], strict=False
        )
        if ipnet.version == 4:
            return ipnet.supernet(netmask[0]).compressed
        else:
            return ipnet.supernet(netmask[1]).compressed
    return _


@functools.singledispatch
def get(_noarg):
    raise ValueError("invalid argument")


@get.register(dict)
def _(config):
    headers = set(config.get("HEADER", []))
    netmask = config.get("IP")
    # ipv4, ipv6, default ipv6 (ipv4 is too fragmented)
    if "REMOTE_ADDR" in headers:
        headers.remove("REMOTE_ADDR")
        if not netmask:
            netmask = True
    if isinstance(netmask, str):
        netmask = netmask.split("/", 1)
    if isinstance(netmask, (tuple, list)):
        # turn mask into difference:
        if len(netmask) == 1:
            netmask = (0, 128 - int(netmask[0]))
        else:
            netmask = (32 - int(netmask[0]), 128 - int(netmask[1]))
        assert(netmask[0] >= 0)
        assert(netmask[1] >= 0)
    if netmask == (32, 128):
        netmask = True

    headers = list(sorted(headers))
    session_keys = list(sorted(set(config.get("SESSION", []))))
    sorted_args = set(config.get("POST", []))
    sorted_args.update(set(config.get("GET", [])))
    sorted_args = list(sorted(sorted_args))

    def _ret_fun(request, group):
        ret = []
        if netmask is True:
            ret.append(ipaddress.ip_network(
                request.META['REMOTE_ADDR'], strict=False
            ).compressed)
        elif netmask:
            ipnet = ipaddress.ip_network(
                request.META['REMOTE_ADDR'], strict=False
            )
            if ipnet.version == 4:
                ret.append(ipnet.supernet(netmask[0]).compressed)
            else:
                ret.append(ipnet.supernet(netmask[1]).compressed)
        if config.get("USER") and request.user.is_authenticated:
            ret.append(str(request.user.pk))
        for arg in session_keys:
            if arg is None:
                if request.session.session_key:
                    ret.append(request.session.session_key)
            elif arg in request.session:
                ret.append(request.session[arg])
        for arg in headers:
            if arg in request.META:
                ret.append(request.META[arg])
        for arg in sorted_args:
            if arg in request.POST:
                ret.append(request.POST[arg])
            if arg in request.GET:
                ret.append(request.GET[arg])
        return "".join(ret)
    return _ret_fun


@get.register(str)
def _(*args):
    g = {
        "IP": False,
        "USER": False,
        "SESSION": False,
        "HEADER": [],
        "GET": [],
        "POST": []
    }
    for arg in args:
        s = arg if isinstance(arg, (tuple, list)) else str(arg).split(":", 1)
        uppername = s[0].upper()
        s = s[1] if len(s) > 1 else None
        if uppername in {"IP", "USER"}:
            g[uppername] = True if s is None else s
        elif s:
            g[uppername].append(s)
    return get(g)


@functools.singledispatch
def user_and_ip(request, group):
    return get({"IP": True, "USER": True})(request, group)


@user_and_ip.register(str)
def _(netmask):
    return get({"IP": netmask or True, "USER": True})


user = get({"USER": True})


@functools.singledispatch
def ip(request, group):
    return get({"IP": True})(request, group)


@ip.register(str)
def _(netmask):
    return get({"IP": netmask})
