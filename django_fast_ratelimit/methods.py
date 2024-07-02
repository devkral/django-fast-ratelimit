__all__ = [
    "user_or_ip",
    "user_and_ip",
    "ip",
    "user",
    "get",
    "ip_exempt_user",
    "user_or_ip_exempt",
    "static",
]

import functools
from typing import Optional

from django.http import HttpRequest

from .misc import Action
from .misc import get_ip as _get_ip
from .misc import parse_ip_to_net as _parse_ip_to_net
from .misc import protect_sync_only as _protect_sync_only


def _ip_to_net(args=None):
    if not args or args is True:
        args = (128,)

    if isinstance(args, str):
        args = args.split("/")
    args = tuple(map(int, args))
    assert len(args) <= 2
    if len(args) == 1:
        assert args[0] >= 0
        assert args[0] <= 128

        def _(request):
            net, is_ipv4 = _parse_ip_to_net(_get_ip(request))
            return net.supernet(new_prefix=args[0])

        return _

    else:
        assert args[0] >= 0
        assert args[0] <= 32
        assert args[1] >= 0
        assert args[1] <= 128

        def _(request):
            net, is_ipv4 = _parse_ip_to_net(_get_ip(request))
            if is_ipv4:
                return net.supernet(new_prefix=96 + args[0])

            else:
                return net.supernet(new_prefix=args[1])

        return _


_ip_to_net_single = _ip_to_net()


def _get_user_pk_as_str_or_none(request) -> Optional[str]:
    if not hasattr(request, "user"):
        return None
    if (
        request.user.is_active
        and request.user.is_authenticated
        and getattr(request.user, "pk", None)
    ):
        return "user:%s" % request.user.pk
    return None


def _get_user_privileged(
    request, user_ok=False, staff_ok=False, permissions=()
) -> Optional[str]:
    if not hasattr(request, "user"):
        return False
    if request.user.is_active and request.user.is_authenticated:
        if user_ok:
            return True
        if permissions:
            # includes superuser check
            if request.user.has_perms(permissions):
                return True
        elif getattr(request.user, "is_superuser", False):
            return True
        if staff_ok and getattr(request.user, "is_staff", False):
            return True
    return False


@functools.singledispatch
def static(key):
    if not isinstance(key, bytes):
        key = str(key).encode("utf8")
    return lambda request, group, action, rate: static(
        request, group, action, rate, key=key
    )


@static.register(HttpRequest)
def _(request: HttpRequest, group, action, rate, key=b"static"):
    return key


@functools.singledispatch
@_protect_sync_only
def user_or_ip(request: HttpRequest, group, action, rate, ip_fn=_ip_to_net_single):
    user = _get_user_pk_as_str_or_none(request)
    if user:
        return user
    net = ip_fn(request)
    return net.exploded


@user_or_ip.register(str)
@user_or_ip.register(list)
@user_or_ip.register(tuple)
def _(netmask):
    ip_fn = _ip_to_net(netmask)

    return _protect_sync_only(
        functools.partial(user_or_ip.dispatch(HttpRequest).__wrapped__, ip_fn=ip_fn)
    )


@functools.singledispatch
@_protect_sync_only
def user_or_ip_exempt(
    request: HttpRequest,
    group,
    action,
    rate,
    ip_fn=_ip_to_net_single,
    permissions=(),
    user_ok=False,
    staff_ok=False,
    use_user_pk=True,
    invert=False,
):
    if (
        _get_user_privileged(
            request, staff_ok=staff_ok, user_ok=user_ok, permissions=permissions
        )
        != bool(action in {Action.RESET, Action.RESET_EPOCH})
    ) != invert:
        return 0
    if use_user_pk:
        user = _get_user_pk_as_str_or_none(request)
        if user:
            return user
    net = ip_fn(request)
    if not net:
        # block
        return 1
    return net.exploded


@user_or_ip_exempt.register(str)
@user_or_ip_exempt.register(list)
@user_or_ip_exempt.register(tuple)
def _(args, **kwargs):
    if isinstance(args, str):
        args = args.split(",")
    netmask = True
    permissions = []
    flags = set()
    for arg in args:
        if isinstance(arg, str):
            if arg.startswith("netmask:"):
                netmask = arg.split(":", 1)[-1]
            elif arg.startswith("permission:"):
                permissions.append(arg.split(":", 1)[-1])
            else:
                flags.add(arg.lower())
        elif isinstance(arg, (tuple, list)) and len(arg) >= 2:
            if arg[0] == "netmask":
                netmask = tuple(arg[1:])
            elif arg[0] == "permission":
                permissions.extend(arg[1:])
    if "not_use_ip" in flags:
        assert netmask is True, "setting netmask despite not using ip"

        def ip_fn(request):
            return None
    else:
        ip_fn = _ip_to_net(netmask)
    return _protect_sync_only(
        functools.partial(
            user_or_ip_exempt.dispatch(HttpRequest).__wrapped__,
            ip_fn=ip_fn,
            permissions=permissions,
            user_ok="user_ok" in flags,
            staff_ok="staff_ok" in flags,
            use_user_pk="not_use_user_pk" not in flags,
            invert="invert" in flags,
        )
    )


ip_exempt_user = functools.singledispatch(
    _protect_sync_only(
        functools.partial(
            user_or_ip_exempt.dispatch(HttpRequest).__wrapped__,
            user_ok=True,
            use_user_pk=False,
        )
    )
)


@ip_exempt_user.register(str)
@ip_exempt_user.register(list)
@ip_exempt_user.register(tuple)
def _(args):
    if isinstance(args, str):
        args = args.split(",")
    netmask = True
    invert = False
    for arg in args:
        if arg in {"true", "false"}:
            invert = arg == "true"
        else:
            netmask = arg
    ip_fn = _ip_to_net(netmask)
    return _protect_sync_only(
        functools.partial(
            user_or_ip_exempt.dispatch(HttpRequest).__wrapped__,
            user_ok=True,
            use_user_pk=False,
            ip_fn=ip_fn,
            invert=invert,
        )
    )


@functools.singledispatch
def get(_noarg, group, action, rate):
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
    ip_fn = None
    if netmask:
        ip_fn = _ip_to_net(netmask)

    headers = list(sorted(headers))
    session_keys = list(sorted(set(config.get("SESSION", []))))
    post_set = set(config.get("POST", []))
    get_set = set(config.get("GET", []))
    sorted_args = list(sorted(post_set | get_set))
    check_user = config.get("USER", False)
    assert isinstance(check_user, bool), "USER can only be boolean"

    def _generate_key(request):
        if ip_fn:
            ip = ip_fn(request)
            yield ip.exploded
        if check_user:
            user = _get_user_pk_as_str_or_none(request)
            if user:
                yield user
        for arg in session_keys:
            if arg is None:
                if request.session.session_key:
                    yield request.session.session_key
            elif arg in request.session:
                yield request.session[arg]
        for arg in headers:
            if arg in request.META:
                yield request.META[arg]
        for arg in sorted_args:
            if arg in post_set:
                # empty values will be ignored
                yield request.POST.get(arg, "")
            if arg in get_set:
                # empty values will be ignored
                yield request.GET.get(arg, "")

    if check_user:
        return _protect_sync_only(
            lambda request, group, action, rate: "".join(_generate_key(request))
        )
    else:
        return lambda request, group, action, rate: "".join(_generate_key(request))


@get.register(str)
def _(*args):
    if len(args) == 1:
        args = args[0].split(",")
    g = {
        "IP": False,
        "USER": False,
        "SESSION": False,
        "HEADER": [],
        "GET": [],
        "POST": [],
    }
    for arg in args:
        # split argument in list
        s = arg if isinstance(arg, (tuple, list)) else str(arg).split(":", 1)
        uppername = s[0].upper()
        value = s[1] if len(s) > 1 else None
        if uppername in {"IP", "USER"}:
            g[uppername] = True if value is None else value
        elif uppername == "SESSION":
            # can be None
            g[uppername].append(value)
        elif value:
            g[uppername].append(value)
    return get(g)


@functools.singledispatch
def user_and_ip(request: HttpRequest, group, action, rate):
    return get({"IP": True, "USER": True})(request, group, action, rate)


@user_and_ip.register(str)
def _(netmask):
    return get({"IP": netmask, "USER": True})


user = get({"USER": True})


ip = functools.singledispatch(get({"IP": True}))


@ip.register(str)
@ip.register(list)
@ip.register(tuple)
def _(netmask):
    return get({"IP": netmask})
