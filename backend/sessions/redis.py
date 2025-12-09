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



redis_client = RedisClient()
