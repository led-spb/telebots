import random
import json
from pytelegram_async.bot import Bot
from tornado import gen
from tornado.web import HTTPError


class DummyBot(Bot):
    def __init__(self):
        self.messages = []
        self.admin = random.randint(0, 100000)
        Bot.__init__(self, token=None, admins=[self.admin])

    def clear(self):
        self.messages = []

    @gen.coroutine
    def send_message(self, to, message, callback=None, reply_markup=None, **extra):
        self.messages.append({"to": to, "message": message})
        print str(message)

        raise gen.Return(DummyHTTPResponse(
            code=200, headers={}, body=json.dumps({"result": {"message_id": random.randint(0, 100000)}})
        ))


class DummyMqttClient(object):
    def subscribe(self, topic):
        pass


class DummyMqttMessage(object):
    pass


class DummyHTTPResponse(object):
    def __init__(self, **kwargs):
        map(lambda item: setattr(self, item[0], item[1]), kwargs.items())

    def rethrow(self):
        if hasattr(self, 'code') and getattr(self, 'code') >= 399:
            raise HTTPError(code=getattr(self, 'code'), message="HTTPError")
        pass


class DummyHTTPClient(object):
    def __init__(self, random_delay=0):
        self.random_delay = random_delay
        self.responses = []

    @gen.coroutine
    def fetch(self, *args, **kwargs):
        if self.random_delay >= 0:
            yield gen.sleep(self.random_delay)
        raise gen.Return(self.responses.pop(0))
        pass

    def add(self, **kwargs):
        self.responses.append(DummyHTTPResponse(**kwargs))
