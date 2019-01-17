from dummy_objects import DummyBot, DummyMqttClient, DummyMqttMessage
import telebots
from telebots.homebot import HomeBotHandler
import pytelegram_async.entity
import pytest
import urlparse
import uuid
import random


@pytest.fixture
def handler():
    bot = DummyBot()
    dummy_mqtt = DummyMqttClient()

    handler = HomeBotHandler(
        ioloop=None,
        mqtt_url=urlparse.urlparse('mqtt://dummy/'),
        sensors=["door://sensor 1@home/sensor/test", "presence://wireless_sensor@home/wireless/00:AA:BB:CC"],
        cameras=["+"]
    )
    handler.on_mqtt_connect(dummy_mqtt, None, None, 0)
    bot.add_handler(handler)
    yield handler


class TestHomeBot(object):
    def test_version(self, handler):
        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": 1234},
                "text": "/version"
            }
        )
        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == 1234
        assert handler.bot.messages[0]['message'] == str(telebots.version)

    def test_unauth(self, handler):
        user_id = handler.bot.admin + random.randint(1, 10000)

        # /photo
        assert not handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": -1}, "text": "/photo"}
        )
        assert len(handler.bot.messages) == 0
        # /video
        assert not handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": -1}, "text": "/photo"}
        )
        assert len(handler.bot.messages) == 0
        # /sub
        assert not handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": -1}, "text": "/sub"}
        )
        assert len(handler.bot.messages) == 0
        # /status
        assert not handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": -1}, "text": "/status"}
        )
        assert len(handler.bot.messages) == 0
        # random not command
        assert not handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": -1}, "text": str(uuid.uuid4())}
        )
        assert len(handler.bot.messages) == 0

    def test_photo(self, handler):
        chat_id = random.randint(1, 100000)

        assert handler.bot.exec_command(
            message={"from": {"id": handler.bot.admin}, "chat": {"id": chat_id}, "text": "/photo"}
        )

        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/camera/test/photo'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == len(handler.bot.admins)
        message = handler.bot.messages.pop()
        assert message['to'] == handler.bot.admin
        assert isinstance(message['message'], pytelegram_async.entity.Photo)

    def test_status(self, handler):
        chat_id = random.randint(1, 100000)

        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/wireless/00:AA:BB:CC'
        message.payload = '1'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == len(handler.bot.admins)
        message = handler.bot.messages.pop()
        assert message['to'] == handler.bot.admin
        handler.bot.clear()

        assert handler.bot.exec_command(
            message={"from": {"id": handler.bot.admin}, "chat": {"id": chat_id}, "text": "/status"}
        )
        assert len(handler.bot.messages) == len(handler.bot.admins)
        for message in handler.bot.messages:
            assert message['to'] == chat_id

    def test_event_notify(self, handler):
        handler.bot.clear()

        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/notify'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == len(handler.bot.admins)
        assert handler.bot.messages[0]['to'] == handler.bot.admin
        assert handler.bot.messages[0]['message'] == message.payload

    def test_event_photo(self, handler):
        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/camera/test/photo'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == len(handler.bot.admins)
        assert handler.bot.messages[0]['to'] == handler.bot.admin
        assert isinstance(handler.bot.messages[0]['message'], pytelegram_async.entity.Photo)

    def test_event_video(self, handler):
        # 1. Not subscribed
        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/camera/test/video'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == 0

        # 2. Subscribed
        assert handler.bot.exec_command(
            message={"from": {"id": handler.bot.admin}, "chat": {"id": random.randint(0, 10000)}, "text": "/sub"}
        )

        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/camera/test/video'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == 1
        message = handler.bot.messages.pop()
        assert message['to'] == handler.bot.admin
        assert isinstance(message['message'], pytelegram_async.entity.Video)

    def test_event_video_merged(self, handler):
        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/camera/test/videom'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == 1
        message = handler.bot.messages.pop()
        assert message['to'] == handler.bot.admin
        assert isinstance(message['message'], pytelegram_async.entity.Video)

    def test_event_sensor(self, handler):
        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/sensor/test'

        # 1. Off event is not alert
        message.payload = '0'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == 0

        # 2. On event is alert
        message.payload = '1'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == 1
        response = handler.bot.messages.pop()
        assert response['to'] == handler.bot.admin
        handler.bot.clear()

        # 3. Fast Off-On is not alert
        message.payload = '0'
        handler.on_mqtt_message(None, None, message)
        message.payload = '1'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == 0
