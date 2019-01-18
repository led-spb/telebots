#!/usr/bin/python
# -*- coding: utf-8 -*-
import re
import os
import os.path
import logging
import argparse
import time
import datetime
import urlparse
import paho_async.client as mqtt
from cStringIO import StringIO
from pytelegram_async.bot import Bot, BotRequestHandler, PatternMessageHandler
from pytelegram_async.entity import *
from tornado.ioloop import IOLoop
from tornado.httpclient import AsyncHTTPClient
from jinja2 import Environment
from paho.mqtt.client import topic_matches_sub
import humanize
import telebots
from functools import reduce
from sensors import Sensor


class HomeBotHandler(BotRequestHandler, mqtt.TornadoMqttClient):
    def __init__(self, ioloop, admins, mqtt_url, sensors=[]):
        BotRequestHandler.__init__(self)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.ioloop = ioloop

        self.sensors = [self.build_sensor_from_url(url, admins) for url in sensors or []]

        self.trigger_gap = 300
        self.http_client = AsyncHTTPClient()

        self.jinja = Environment()
        self.jinja.filters['human_date'] = self.human_date
        self.sensor_template = self.jinja.from_string(
            "<b>{{sensor.name}}</b>: {{ sensor.state_text() }} {{ sensor.changed | human_date }}"
        )

        self.sensor_full_template = self.jinja.from_string(
            "<b>name</b>: {{sensor.name}}\n"
            "<b>type</b>: {{sensor.type}}\n"
            "<b>state</b>: {{sensor.state_text()}}\n"
            "<b>changed</b>: {{ sensor.changed | human_date }}\n"
            "<b>triggered</b>: {{ sensor.triggered | human_date }}"
        )

        host = mqtt_url.hostname
        port = mqtt_url.port if mqtt_url.port is not None else 1883

        self.logger.info("Trying connect to MQTT broker at %s:%d" % (host, port))

        self.subscribe = False
        mqtt.TornadoMqttClient.__init__(
            self, ioloop=ioloop, host=mqtt_url.hostname,
            port=mqtt_url.port if mqtt_url.port is not None else 1883,
            username=mqtt_url.username, password=mqtt_url.password
        )
        self.version = telebots.version
        pass

    def build_sensor_from_url(self, url, admins):
        sensor = Sensor.from_url(url, admins)
        if sensor.type == "camera":
            sensor.on_changed = self.event_camera
        elif sensor.type == "notify":
            sensor.on_changed = self.event_notify
        else:
            sensor.on_changed = self.event_sensor
        return sensor

    def sensor_by_name(self, name):
        return reduce(lambda x, y: x if x.name == name else y, self.sensors + [None])

    @staticmethod
    def human_date(value):
        if isinstance(value, float) or isinstance(value, int):
            value = datetime.datetime.fromtimestamp(value)
        return humanize.naturaltime(value)

    def on_mqtt_connect(self, client, obj, flags, rc):
        self.logger.info("MQTT broker: %s", mqtt.connack_string(rc))
        if rc == 0:
            # Subscribe sensors topics
            for sensor in self.sensors:
                client.subscribe(sensor.topic)
        pass

    def on_mqtt_message(self, client, obj, message):
        if message.retain:
            return
        self.logger.info("topic %s, payload: %s" % (
            message.topic,
            "[binary]" if len(message.payload) > 10 else message.payload
        ))
        for sensor in self.sensors:
            if topic_matches_sub(sensor.topic, message.topic):
                return sensor.process(message.topic, message.payload)
        pass

    @PatternMessageHandler('/photo', authorized=True)
    def cmd_photo(self):
        self.http_client.fetch("http://127.0.0.1:8082/0/action/snapshot")
        return True

    @PatternMessageHandler("/video( .*)?", authorized=True)
    def cmd_video(self, chat, text):
        params = text.split()
        video = params[1] if len(params) > 1 else None

        if video is None:
            files = sorted([x for x in os.listdir('/home/hub/motion')
                            if re.match(r'\d{8}_\d{6}\.mp4', x)], reverse=True)

            buttons = [{
                'callback_data': '/video '+fname,
                'text': re.sub(r'^\d{8}_(\d{2})(\d{2}).*$', '\\1:\\2', fname)
            } for fname in files]
            keyboard = [
                x for x in [
                    buttons[i*7:(i+1)*7] for i in range(len(buttons)/7+1)
                ] if len(x) > 0
            ]
            self.bot.send_message(
                to=chat.get('id'),
                message='which video?',
                reply_markup={'inline_keyboard': keyboard}
            )
        else:
            caption = re.sub(r'^\d{8}_(\d{2})(\d{2}).*$', '\\1:\\2', video)
            self.bot.send_message(
                to=chat.get('id'),
                message=Video(
                    video=File('video.mp4', open('/home/hub/motion/'+video, 'rb'), 'video/mp4'),
                    caption=caption
                )
            )
        return True

    @PatternMessageHandler("/status", authorized=True)
    def cmd_status(self, chat):
        self.notify_sensor(chat['id'])
        return True

    @PatternMessageHandler("/sensor( .*)?", authorized=True)
    def cmd_sensor(self, chat, text, message_id):
        params = text.split()

        def show_menu():
            buttons = [
                {'callback_data': '/sensor %s' % item.name, 'text': item.name}
                for item in self.sensors
            ]
            self.bot.send_message(
                to=chat['id'], message="Which sensor?",
                reply_markup={'inline_keyboard': [buttons, [{'callback_data': '/sensor', 'text': 'Back'}]]},
                parse_mode='HTML'
            )

        def show_sensor_menu(sensor):
            buttons = [
                {'callback_data': '/sensor %s 1' % sensor.name, 'text': 'Subscribe'},
                {'callback_data': '/sensor %s 0' % sensor.name, 'text': 'Unsubscribe'}
            ]
            message = self.sensor_full_template.render(sensor=sensor)
            self.bot.edit_message_text(
                to=chat['id'], message_id=message_id, text=message,
                reply_markup={
                    'inline_keyboard': [
                        buttons,
                        [{'callback_data': '/sensor %s' % sensor.name, 'text': 'Back'}]
                    ]
                },
                parse_mode='HTML'
            )
            pass

        if len(params) == 1:
            show_menu()
        elif len(params) == 2:
            sensor = self.sensor_by_name(params[1])
            if sensor is None:
                show_menu()
            else:
                show_sensor_menu(sensor)
            pass
        if len(params)==3:
            sensor = self.sensor_by_name(params[1])
            if sensor is None:
                show_menu()
                return True
            if int(params[2]) > 0:
                sensor.add_subscription(chat['id'])
            else:
                sensor.remove_subscription(chat['id'])

            if message_id is not None:
                self.bot.edit_message_text(
                    to=chat['id'], message_id=message_id, text='Sensor <b>%s</b> changed' % sensor.name,
                    parse_mode='HTML'
                )
        return True

    def notify_sensor(self, chat_id, sensor=None):
        messages = [
            self.sensor_template.render(sensor=item)
            for item in self.sensors
            if (sensor is None or item == sensor) and not item.is_dummy
        ]
        return self.bot.send_message(to=chat_id, message="\n".join(messages), parse_mode='HTML')

    @PatternMessageHandler('/camera (\S+)', authorized=True)
    def cmd_camera(self, chat, text):
        params = text.split()
        if len(params) != 2:
            return
        camera = self.sensor_by_name(params[1])
        if camera is not None and chat['id'] not in camera.one_time_sub:
            camera.one_time_sub.append(chat['id'])
        return True

    def event_camera(self, camera):
        event_type = camera.event_type
        self.logger.info("Camera sensor %s triggered for event %s", camera.name, camera.event_type)

        # Photo events send only subscribers
        if event_type == 'photo':
            markup = {
                    'inline_keyboard': [[{
                        'text': 'Subscribe',
                        'callback_data': '/camera %s' % camera.name
                    }]]
            }
            for chat_id in camera.subscriptions:
                self.bot.send_message(
                    to=chat_id,
                    message=Photo(
                        photo=File('image.jpg', StringIO(camera.state), 'image/jpeg'),
                        caption='camera#%s' % camera.name
                    ),
                    reply_markup=markup
                )
            return None

        if event_type == 'videom':
            for chat_id in camera.subscriptions:
                self.bot.send_message(
                    to=chat_id,
                    message=Video(
                        video=File('camera_%s.mp4' % camera.name, StringIO(camera.state), 'video/mp4')
                    )
                )

        if event_type == 'video':
            for chat_id in camera.one_time_sub:
                self.bot.send_message(
                    to=chat_id,
                    message=Video(
                        video=File('camera_%s.mp4' % camera.name, StringIO(camera.state), 'video/mp4')
                    )
                )
            camera.one_time_sub = []
        pass

    def event_notify(self, sensor):
        self.logger.info("Notify sensor %s triggered", sensor.name)
        for chat_id in sensor.subscriptions:
            self.bot.send_message(
                to=chat_id,
                message="<b>%s</b>: %s" % (sensor.name, sensor.state),
                parse_mode='HTML'
            )
        pass

    def event_sensor(self, sensor):
        self.logger.info("Sensor %s changed to %d", sensor.name, sensor.state)
        status = sensor.state
        now = time.time()

        if status > 0 and (now-sensor.triggered) > self.trigger_gap:
            sensor.triggered = now
            for chat_id in sensor.subscriptions:
                self.notify_sensor(chat_id, sensor)
        pass


def main():

    class LoadFromFile(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            with values as f:
                parser.parse_args(f.read().split(), namespace)

    parser = argparse.ArgumentParser(fromfile_prefix_chars='@')

    basic = parser.add_argument_group('basic', 'Basic parameters')
    basic.add_argument("-c", "--config", type=open, action=LoadFromFile, help="Load config from file")
    basic.add_argument("-u", "--url", default="mqtt://localhost:1883", type=urlparse.urlparse,
                       help="MQTT Broker address host:port")
    basic.add_argument("--token", help="Telegram API bot token")
    basic.add_argument("--admin", nargs="+", help="Bot admin", type=int, dest="admins")
    basic.add_argument("--proxy")
    basic.add_argument("--logfile", help="Logging into file")
    basic.add_argument("-v", action="store_true", default=False, help="Verbose logging", dest="verbose")

    status = parser.add_argument_group('status', 'Home state parameters')
    status.add_argument("--sensors", nargs="*", help="Sensor in URL format: type://name[!]@mqtt_topic")

    args = parser.parse_args()

    # configure logging
    logging.basicConfig(
        format="[%(asctime)s]\t[%(levelname)s]\t[%(name)s]\t%(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
        filename=args.logfile
    )
    logging.info("Starting telegram bot")
    ioloop = IOLoop.instance()
    bot = Bot(args.token, args.admins, proxy=args.proxy, ioloop=ioloop)
    handler = HomeBotHandler(ioloop=ioloop, admins=bot.admins, mqtt_url=args.url, sensors=args.sensors)
    bot.add_handler(handler)
    bot.loop_start()
    handler.start()
    try:
        ioloop.start()
    except KeyboardInterrupt:
        ioloop.stop()
    pass


if __name__ == '__main__':
    main()
