import time
from timezonefinder import TimezoneFinder
import logging

def rate_limit(max_requests):
    """Max request per second."""
    def decorator(func):
        last_called = [0.0]  # Use a mutable object to store the timestamp

        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            if elapsed < 1 / max_requests:
                time.sleep((1 / max_requests) - elapsed)

            last_called[0] = time.time()
            return func(*args, **kwargs)

        return wrapper

    return decorator

def cache_results(func):
    cache = {}

    def wrapper(*args):
        if args in cache:
            logging.debug(f"Cache hit for coordinates: {args}")
            return cache[args]
        result = func(*args)
        cache[args] = result
        return result

    return wrapper


tf = TimezoneFinder()

@cache_results
def find_timezone_coarse(longitude: float, latitude: float) -> str:
    logging.debug(f"Finding timezone for coordinates: ({latitude}, {longitude})")
    timezone = tf.timezone_at(lng=longitude, lat=latitude)
    if timezone is None:
        logging.warning(f"Could not find timezone for coordinates: ({latitude}, {longitude}). Returning UTC as default.")
        return "UTC"  # Default to UTC if timezone cannot be determined
    logging.debug(f"Found timezone: {timezone} for coordinates: ({latitude}, {longitude})")
    return timezone


def find_timezone(longitude: float, latitude: float) -> str:
    return find_timezone_coarse(round(longitude, 4), round(latitude, 4))


