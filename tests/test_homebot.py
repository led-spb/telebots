from dummy_bot import DummyBot, DummyMqttMessage
import telebots
from telebots.homebot import HomeBotHandler
import pytelegram_async.entity
import pytest
import urlparse
import uuid


class TestHomeBot:

    @pytest.fixture
    def handler(self):
        bot = DummyBot()

        handler = HomeBotHandler(
            ioloop=None,
            mqtt_url=urlparse.urlparse('mqtt://dummy/'),
            sensors=["sensor 1@home/sensor/test", "sensor 2?@test/topic2"]
        )
        bot.add_handler(handler)
        yield handler

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

    def test_photo_unauth(self, handler):
        assert not handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin + 1000},
                "chat": {"id": -1},
                "text": "/photo"
            }
        )
        assert len(handler.bot.messages) == 0

    def test_photo_common(self, handler):
        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": -1},
                "text": "/photo"
            }
        )

        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/camera/test/photo'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == len(handler.bot.admins)
        assert handler.bot.messages[0]['to'] == handler.bot.admin
        assert isinstance(handler.bot.messages[0]['message'], pytelegram_async.entity.Photo)

    def test_status_common(self, handler):
        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/sensor/test'
        message.payload = '1'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == len(handler.bot.admins)
        assert handler.bot.messages[0]['to'] == handler.bot.admin
        handler.bot.clear()

        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": 1234},
                "text": "/status"
            }
        )
        assert len(handler.bot.messages) == len(handler.bot.admins)*len(handler.sensors)
        assert handler.bot.messages[0]['to'] == 1234

    def test_video_unauth(self, handler):
        assert not handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin + 1000},
                "chat": {"id": -1},
                "text": "/video"
            }
        )
        assert len(handler.bot.messages) == 0

    def test_sub_unauth(self, handler):
        assert not handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin + 1000},
                "chat": {"id": -1},
                "text": "/sub"
            }
        )
        assert len(handler.bot.messages) == 0

    def test_status_unauth(self, handler):
        assert not handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin + 1000},
                "chat": {"id": -1},
                "text": "/status"
            }
        )
        assert len(handler.bot.messages) == 0

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

    def test_event_video_not_subscribed(self, handler):
        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/camera/test/video'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == 0

    def test_event_video_subscribed(self, handler):
        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": -1},
                "text": "/sub"
            }
        )

        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/camera/test/video'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == handler.bot.admin
        assert isinstance(handler.bot.messages[0]['message'], pytelegram_async.entity.Video)

    def test_event_video_merged(self, handler):
        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/camera/test/videom'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == handler.bot.admin
        assert isinstance(handler.bot.messages[0]['message'], pytelegram_async.entity.Video)

    def test_event_sensor(self, handler):
        message = DummyMqttMessage()
        message.retain = False
        message.topic = 'home/sensor/test'

        # Off event is not alert
        message.payload = '0'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == 0

        # On event is alert
        message.payload = '1'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == handler.bot.admin
        handler.bot.clear()

        # Fast Off-On is not alert
        message.payload = '0'
        handler.on_mqtt_message(None, None, message)
        message.payload = '1'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == 0
