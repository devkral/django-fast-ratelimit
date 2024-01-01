"""
private helpers for epoch stuff
"""

from typing import Optional

from django.core.cache import BaseCache


def epoch_call_count(epoch, cache_key, delta=1) -> Optional[int]:
    if epoch is None or isinstance(epoch, int):
        return epoch
    if not hasattr(epoch, "_fast_ratelimit_dict_count"):
        setattr(epoch, "_fast_ratelimit_dict_count", {})
    counter_dict = getattr(epoch, "_fast_ratelimit_dict_count")
    count = counter_dict.get(cache_key, 0) + delta
    if delta != 0:
        counter_dict[cache_key] = count
    return count


def reset_epoch(epoch, cache: BaseCache, cache_key: str) -> Optional[int]:
    call_count = epoch_call_count(epoch, cache_key, 0)
    try:
        # decr does not extend cache duration
        count = cache.decr(cache_key, call_count)
    except ValueError:
        count = None
    epoch_call_count(epoch, cache_key, -call_count)
    return count


async def areset_epoch(epoch, cache, cache_key) -> Optional[int]:
    call_count = epoch_call_count(epoch, cache_key, 0)
    try:
        # decr does not extend cache duration
        count = await cache.adecr(cache_key, call_count)
    except ValueError:
        count = None
    epoch_call_count(epoch, cache_key, -call_count)
    return count
