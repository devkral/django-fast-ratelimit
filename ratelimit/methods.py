__all__ = ["user_or_ip", "user_and_ip", "ip", "user", "get"]

import functools


@functools.singledispatch
def user_or_ip(request, group):
    if request.user.is_authenticated:
        return str(request.user.pk)
    return request.META['REMOTE_ADDR']


@user_or_ip.register(str)
def _(netmask):
    def _(request, group):
        if request.user.is_authenticated:
            return str(request.user.pk)
        return request.META['REMOTE_ADDR']
    return _


@functools.singledispatch
def get(_noarg=None):
    raise ValueError("invalid argument")


@get.register(dict)
def _(config):
    ipactive = config.get("IP")
    headers = set(config.get("HEADER", []))
    if "REMOTE_ADDR" in headers:
        headers.remove("REMOTE_ADDR")
        if not ipactive:
            ipactive = True
    headers = list(sorted(headers))
    session_keys = list(sorted(set(config.get("SESSION", []))))
    sorted_args = set(config.get("POST", []))
    sorted_args.update(set(config.get("GET", [])))
    sorted_args = list(sorted(sorted_args))

    def _ret_fun(request, group):
        ret = []
        if ipactive:
            ret.append(request.META["REMOTE_ADDR"])
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
