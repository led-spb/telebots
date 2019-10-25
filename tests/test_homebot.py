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
        admins=bot.admins,
        sensors=[
            "door://sensor_1@home/sensor/test",
            "door://sensor_2!@home/sensor/test2",
            "presence://wireless_sensor@home/wireless/00:AA:BB:CC",
            "notify://notify@home/notify",
            "camera://test@home/camera/test"
        ],
        extra_cmds={
            '/photo': 'cmd /C dir'
        }
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
        # /sensor
        assert not handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": -1}, "text": "/sensor"}
        )
        # /camera
        assert not handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": -1}, "text": "/camera"}
        )
        assert len(handler.bot.messages) == 0
        # /video
        assert not handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": -1}, "text": "/photo"}
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

    def test_sensor(self, handler):
        test_sensor = [x for x in handler.sensors if not x.is_dummy].pop()

        chat_id = random.randint(1, 100000)

        # /sensor
        assert handler.bot.exec_command(
            message={"from": {"id": handler.bot.admin}, "chat": {"id": chat_id}, "text": "/sensor"}
        )
        assert len(handler.bot.messages) == 1
        message = handler.bot.messages.pop()
        assert message['to'] == chat_id
        assert message['message'] == "Which sensor?"

        # /sensor sensor_name
        assert handler.bot.exec_command(
            message={"from": {"id": handler.bot.admin},
                     "chat": {"id": chat_id},
                     "text": "/sensor %s" % test_sensor.name}
        )
        assert len(handler.bot.messages) == 1
        message = handler.bot.messages.pop()
        assert message['to'] == chat_id
        assert test_sensor.name in message['message']

        # /sensor sensor_name 1
        assert handler.bot.exec_command(
            message={"from": {"id": handler.bot.admin},
                     "chat": {"id": chat_id},
                     "text": "/sensor %s 1" % test_sensor.name}
        )
        assert len(handler.bot.messages) == 1
        assert test_sensor.subscriptions.pop() == chat_id

    def test_status(self, handler):
        chat_id = random.randint(1, 100000)
        test_sensor = [x for x in handler.sensors if not x.is_dummy and x.is_subscribed(handler.bot.admin)].pop()

        message = DummyMqttMessage()
        message.retain = False
        message.topic = test_sensor.topic
        message.payload = '1'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == len(test_sensor.subscriptions) and len(test_sensor.subscriptions) > 0
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
        test_sensor = [
            x for x in handler.sensors if x.is_dummy and x.is_subscribed(handler.bot.admin) and x.type == 'notify'
        ][0]
        handler.bot.clear()

        message = DummyMqttMessage()
        message.retain = False
        message.topic = test_sensor.topic
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == len(test_sensor.subscriptions)
        assert handler.bot.messages[0]['to'] == handler.bot.admin
        assert message.payload in handler.bot.messages[0]['message']

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
        test_camera = [x for x in handler.sensors if x.type == 'camera'].pop()

        # 1. Video from not subscribed camera
        message = DummyMqttMessage()
        message.retain = False
        message.topic = test_camera.topic.strip('#')+'video'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == 0

        # 2. Video from one time subscribed camera
        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": handler.bot.admin},
                "text": "/camera %s" % test_camera.name
            }
        )

        message = DummyMqttMessage()
        message.retain = False
        message.topic = test_camera.topic.strip('#')+'video'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == 1
        message = handler.bot.messages.pop()
        assert message['to'] == handler.bot.admin
        assert isinstance(message['message'], pytelegram_async.entity.Video)

    def test_event_video_merged(self, handler):
        test_camera = [x for x in handler.sensors if x.type == 'camera'].pop()

        message = DummyMqttMessage()
        message.retain = False
        message.topic = test_camera.topic.strip('#')+'videom'
        message.payload = str(uuid.uuid4())
        handler.on_mqtt_message(None, None, message)

        assert len(handler.bot.messages) == 1
        message = handler.bot.messages.pop()
        assert message['to'] == handler.bot.admin
        assert isinstance(message['message'], pytelegram_async.entity.Video)

    def test_event_sensor_subscribed(self, handler):
        test_sensor = [x for x in handler.sensors if not x.is_dummy and x.is_subscribed(handler.bot.admin)][0]

        message = DummyMqttMessage()
        message.retain = False
        message.topic = test_sensor.topic

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

    def test_event_unsubscribed(self, handler):
        # 4. Event on unsubscribed sensor
        test_sensor = [x for x in handler.sensors if not x.is_dummy and not x.is_subscribed(handler.bot.admin)][0]
        message = DummyMqttMessage()
        message.retain = False
        message.topic = test_sensor.topic
        message.payload = '1'
        handler.on_mqtt_message(None, None, message)
        assert len(handler.bot.messages) == 0
