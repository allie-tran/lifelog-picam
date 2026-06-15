import redis
import json

class RedisClient:
    def __init__(self, host='localhost', port=6379, db=0):
        self.client = redis.StrictRedis(host=host, port=port, db=db)

    def set_value(self, key, value):
        self.client.set(key, value)

    def get_value(self, key):
        return self.client.get(key)

    def delete_value(self, key):
        self.client.delete(key)

    def get_json(self, key):
        value = self.get_value(key)
        if value:
            return json.loads(value)
        return None

    def set_json(self, key, data):
        self.set_value(key, json.dumps(data))

    def set_with_ttl(self, key, value, ttl_seconds: int):
        self.client.set(key, value, ex=ttl_seconds)

    def set_json_with_ttl(self, key, data, ttl_seconds: int):
        self.set_with_ttl(key, json.dumps(data), ttl_seconds)

    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a glob pattern. Returns count deleted."""
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = self.client.scan(cursor, match=pattern, count=100)
            if keys:
                deleted += self.client.delete(*keys)
            if cursor == 0:
                break
        return deleted

    def get_ttl(self, key):
        return self.client.ttl(key)


redis_client = RedisClient()


def bust_day_caches(device: str, date: str) -> None:
    """Delete every browse/day-nav cache for a device+date, across all key shapes:
    browse:day:<dev>:<date>, browse:segment:<dev>:<date>:*, browse:<dev>:<date>:<hour>,
    day-nav:v2:<dev>:<date>, segs_complete:<dev>:<date>. The glob `*` spans ':' so one
    pattern per family covers every variant (and future cache-key version bumps).
    """
    redis_client.delete_pattern(f"browse:*{device}:{date}*")
    redis_client.delete_pattern(f"day-nav:*{device}:{date}")
    redis_client.delete_value(f"segs_complete:{device}:{date}")
