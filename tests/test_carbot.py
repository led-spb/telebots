import telebots
from telebots.carbot import CarMonitor
import pytelegram_async.entity
import pytest
import urlparse
import json
from dummy_bot import DummyBot, DummyMqttMessage


class TestCarBot:

    @pytest.fixture
    def handler(self):
        bot = DummyBot()

        monitor = CarMonitor(
            ioloop=None,
            url=urlparse.urlparse('mqtt://dummy/'),
            name='test',
            track_path='.',
            api_key=None
        )
        bot.add_handler(monitor)
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
        message.topic = "owntracks/"+monitor.name+"/tracker"
        message.payload = json.dumps(payload)
        message.retain = True

        monitor.on_mqtt_message(
            client=None, userdata=None,
            message=message
        )
        yield monitor

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

    def test_track_unauth(self, handler):
        assert not handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin + 1000},
                "chat": {"id": -1},
                "text": "/track test.gpx"
            }
        )
        assert len(handler.bot.messages) == 0


    def test_track_common(self, handler):
        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": 1234},
                "text": "/track"
            }
        )
        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == 1234
        assert handler.bot.messages[0]['message'] == 'which track?'

    def test_track_wrong_track(self, handler):
        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": 1234},
                "text": "/track qwerty.gpx"
            }
        )
        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == 1234
        assert handler.bot.messages[0]['message'] == 'No tracks'

    def test_info_unauth(self, handler):
        assert not handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin + 1000},
                "chat": {"id": -1},
                "text": "/info"
            }
        )
        assert len(handler.bot.messages) == 0

    def test_info_common(self, handler):
        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": -1},
                "text": "/info"
            }
        )
        assert len(handler.bot.messages) == 1

    def test_location_unauth(self, handler):
        assert not handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin + 1000},
                "chat": {"id": -1},
                "text": "/location"
            }
        )
        assert len(handler.bot.messages) == 0

    def test_location_common(self, handler):
        handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": 3456},
                "text": "/location"
            }
        )
        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == 3456
        assert isinstance(handler.bot.messages[0]['message'], pytelegram_async.entity.Venue)

    def test_events_unauth(self, handler):
        assert not handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin + 1000},
                "chat": {"id": -1},
                "text": "/events"
            }
        )
        assert len(handler.bot.messages) == 0


    def test_events_common(self, handler):
        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": 1234},
                "text": "/events warn"
            }
        )
        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == 1234
        assert not handler.subscriptions[1234]
        handler.bot.clear()

        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": 1234},
                "text": "/events all"
            }
        )
        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == 1234
        assert handler.subscriptions[1234]
        assert not handler.subscriptions[4321]
