import telebots
from telebots.carbot import CarMonitor
import pytelegram_async.entity
import pytest
import urlparse
import json
import random
import uuid
from dummy_objects import DummyBot, DummyMqttMessage


@pytest.fixture(name="carbot")
def make_carbot():
    bot = DummyBot()

    handler = CarMonitor(
        ioloop=None,
        url=urlparse.urlparse('mqtt://dummy/'),
        name='test',
        track_path='.',
        api_key=None
    )
    bot.add_handler(handler)
    payload = {
        "lon": 11.1111,
        "volt": 3,
        "_ver": 4, "ttf": 13256, "acc": 14,
        "_type": "location", "charge": 0, "batt": 23, "sat": "6",
        "alt": 33.33333, "vel": 0,
        "tst": 1547438413,
        "cog": 0,
        "temp": 0,
        "src": "gps",
        "lat": 22.2222
    }
    message = DummyMqttMessage()
    message.topic = "owntracks/" + handler.name + "/tracker"
    message.payload = json.dumps(payload)
    message.retain = True

    handler.on_mqtt_message(client=None, userdata=None, message=message)
    yield handler


class TestCarBot(object):
    def test_version(self, carbot):
        user_id = carbot.bot.admin
        chat_id = random.randint(0, 100000)

        assert carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/version"}
        )
        assert len(carbot.bot.messages) == 1
        message = carbot.bot.messages.pop()
        assert message['to'] == chat_id
        assert message['message'] == str(telebots.version)

    def test_unauth(self, carbot):
        user_id = carbot.bot.admin + random.randint(1, 10000)
        chat_id = random.randint(1, 10000)

        # /track
        assert not carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/track test.gpx"}
        )
        assert len(carbot.bot.messages) == 0
        # /info
        assert not carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/info"}
        )
        assert len(carbot.bot.messages) == 0
        # /location
        assert not carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/location"}
        )
        assert len(carbot.bot.messages) == 0
        # /debug
        assert not carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/debug"}
        )
        assert len(carbot.bot.messages) == 0
        # /events
        assert not carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/events"}
        )
        assert len(carbot.bot.messages) == 0
        # random message
        assert not carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": str(uuid.uuid4())}
        )
        assert len(carbot.bot.messages) == 0

    def test_track(self, carbot):
        user_id = carbot.bot.admin
        chat_id = random.randint(1, 10000)

        assert carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/track"}
        )
        assert len(carbot.bot.messages) == 1
        message = carbot.bot.messages.pop()
        assert message['to'] == chat_id
        assert message['message'] == 'No tracks'

        carbot.bot.clear()
        assert carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/track qwerty.gpx"}
        )
        assert len(carbot.bot.messages) == 1
        message = carbot.bot.messages.pop()
        assert message['to'] == chat_id
        assert message['message'] == 'No tracks'

    def test_info(self, carbot):
        user_id = carbot.bot.admin
        chat_id = random.randint(1, 10000)

        assert carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/info"}
        )
        assert len(carbot.bot.messages) == 1
        message = carbot.bot.messages.pop()
        assert message['to'] == chat_id
        assert isinstance(message['message'], str) or isinstance(message['message'], unicode)

    def test_location(self, carbot):
        user_id = carbot.bot.admin
        chat_id = random.randint(1, 10000)

        assert carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/location"}
        )
        assert len(carbot.bot.messages) == 1
        message = carbot.bot.messages.pop()
        assert message['to'] == chat_id
        assert isinstance(message['message'], pytelegram_async.entity.Venue)

    def test_events(self, carbot):
        user_id = carbot.bot.admin
        chat1_id = random.randint(0, 100000)
        chat2_id = chat1_id + 1000

        assert carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat1_id}, "text": "/events warn"}
        )
        assert len(carbot.bot.messages) == 1
        message = carbot.bot.messages.pop()
        assert message['to'] == chat1_id
        assert not carbot.subscriptions[chat1_id]

        assert carbot.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat2_id}, "text": "/events all"}
        )
        assert len(carbot.bot.messages) == 1
        message = carbot.bot.messages.pop()
        assert message['to'] == chat2_id
        assert not carbot.subscriptions[chat1_id]
        assert carbot.subscriptions[chat2_id]
