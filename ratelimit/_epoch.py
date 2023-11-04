from typing import Optional

from django.core.cache import BaseCache


def epoch_call_count(epoch, cache_key, delta=1) -> Optional[int]:
    if epoch is None or isinstance(epoch, int):
        return epoch
    if not hasattr(epoch, f"_fast_ratelimit_{cache_key}_count"):
        setattr(epoch, f"_fast_ratelimit_{cache_key}_count", 0)
    count = getattr(epoch, f"_fast_ratelimit_{cache_key}_count")
    if delta != 0:
        setattr(epoch, f"_fast_ratelimit_{cache_key}_count", count + delta)
    return count + delta


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
