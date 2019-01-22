from urlparse import urlparse
from itertools import chain
import time


def subclasses(cls):
    return list(chain(cls.__subclasses__(), *[subclasses(x) for x in cls.__subclasses__()]))


class Sensor(object):
    __names__ = ['sensor']
    __states__ = ('alert', 'normal')

    def __init__(self, topic, sensor_type, name, subscriptions=None):
        self._topic = topic
        self._type = sensor_type
        self._name = name
        self._state = 0
        self._changed = 0
        self._triggered = 0
        self._on_changed = None
        self._subscriptions = subscriptions or []
        self.one_time_sub = []
        self.is_dummy = False
        pass

    @property
    def topic(self):
        return self._topic

    @property
    def type(self):
        return self._type

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
        self._changed = time.time()
        if self.on_changed is not None:
            self.on_changed(self)

    @property
    def changed(self):
        return self._changed

    @property
    def triggered(self):
        return self._triggered

    @triggered.setter
    def triggered(self, value):
        self._triggered = value

    @property
    def on_changed(self):
        return self._on_changed

    @on_changed.setter
    def on_changed(self, value):
        self._on_changed = value

    @property
    def subscriptions(self):
        return self._subscriptions

    def add_subscription(self, value):
        if not self.is_subscribed(value):
            self._subscriptions.append(value)

    def is_subscribed(self, value):
        return value in self._subscriptions

    def remove_subscription(self, value):
        if self.is_subscribed(value):
            self._subscriptions.remove(value)

    @classmethod
    def from_url(cls, url, subscriptions=None):
        parsed = urlparse(url)
        topic = parsed.hostname + parsed.path
        sensor_type = parsed.scheme
        name = parsed.username.strip('!')
        default_state = parsed.username.endswith('!')
        # default class
        target_cls = cls

        for sub_class in subclasses(cls):
            if sensor_type in sub_class.__names__:
                target_cls = sub_class
                break
        return target_cls(
            topic=topic, sensor_type=sensor_type, name=name,
            subscriptions=subscriptions if not default_state else None
        )

    def state_text(self):
        return self.__states__[int(not self.state)]

    def process(self, topic, payload):
        self.state = int(payload)


class DoorSensor(Sensor):
    __names__ = ['door']
    __states__ = ['opened', 'closed']


class MotionSensor(Sensor):
    __names__ = ['motion']
    __states__ = ['active', 'passive']


class PresenceSensor(Sensor):
    __names__ = ['presence', 'wireless']
    __states__ = ['home', 'away']


class DeviceSensor(Sensor):
    __names__ = ['device']
    __states__ = ['on', 'off']


class DummySensor(Sensor):
    __names__ = ['notify']

    def __init__(self, topic, sensor_type, name, subscriptions=None):
        Sensor.__init__(self, topic, sensor_type, name, subscriptions)
        self.is_dummy = True

    def process(self, topic, payload):
        self.state = payload

    def state_text(self):
        return "n/a"


class CameraSensor(DummySensor):
    __names__ = ['camera']

    def __init__(self, topic, sensor_type, name, subscriptions=None):
        self.event_type = None
        topic = topic + '/#'
        DummySensor.__init__(self, topic, sensor_type, name, subscriptions)

    def process(self, topic, payload):
        self.event_type = topic.split('/').pop()
        self.state = payload
