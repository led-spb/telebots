import random
from pytelegram_async.bot import Bot

class DummyBot(Bot):
    def __init__(self):
        self.messages = []
        self.admin = random.randint(0, 100000)
        Bot.__init__(self, token=None, admins=[self.admin])

    def clear(self):
        self.messages = []

    def send_message(self, to, message, callback=None, reply_markup=None, **extra):
        self.messages.append({"to": to, "message": message})
        print str(message)


class DummyMqttMessage(object):
    pass
