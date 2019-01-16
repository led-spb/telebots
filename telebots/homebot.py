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
import humanize
import telebots


class Sensor(object):
    __slots__ = ['topic', 'name', 'state', 'changed', 'silence']

    def __init__(self, topic, name, silence=False):
        self.topic = topic
        self.name = name
        self.state = 0
        self.changed = 0
        self.silence = silence
        pass


class HomeBotHandler(BotRequestHandler, mqtt.TornadoMqttClient):
    def __init__(self, ioloop, mqtt_url, sensors=None, cameras=None):
        BotRequestHandler.__init__(self)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.ioloop = ioloop
        self.sensors = {}
        for sensor in sensors or []:
            name, topic = sensor.split('@',2)
            self.sensors[topic] = Sensor(topic=topic, name=name.strip('?'), silence=name.endswith('?'))

        self.cameras = cameras or []
        self.event_gap = 300
        self.http_client = AsyncHTTPClient()

        self.jinja = Environment()
        self.jinja.filters['human_date'] = self.human_date
        self.sensor_template = self.jinja.from_string(
            "<b>{{sensor.name}}</b>: {{ 'alert' if sensor.state > 0 else 'norm'}} {{ sensor.changed | human_date }}"
        )

        host = mqtt_url.hostname
        port = mqtt_url.port if mqtt_url.port is not None else 1883

        self.logger.info("Trying connect to MQTT broker at %s:%d" %
                         (host, port))

        self.subscribe = False
        mqtt.TornadoMqttClient.__init__(
            self, ioloop=ioloop, host=mqtt_url.hostname, port=mqtt_url.port if mqtt_url.port is not None else 1883,
            username=mqtt_url.username, password=mqtt_url.password
        )
        self.version = telebots.version
        pass

    @staticmethod
    def human_date(value):
        if isinstance(value, float) or isinstance(value, int):
            value = datetime.datetime.fromtimestamp(value)
        return humanize.naturaltime(value)

    def on_mqtt_connect(self, client, obj, flags, rc):
        self.logger.info("MQTT broker: %s", mqtt.connack_string(rc))
        if rc == 0:
            topics = ["home/notify"] + \
                     ["%s" % x.topic for x in self.sensors.values()] + \
                     ["home/camera/%s/#" % x for x in self.cameras]
            for topic in topics:
                self.logger.debug("Subscribe for topic %s" % topic)
                client.subscribe(topic)
        pass

    def on_mqtt_message(self, client, obj, message):
        if message.retain:
            return

        self.logger.info("topic %s, payload: %s" % (
            message.topic,
            "[binary]" if len(message.payload) > 10 else message.payload
        ))
        path = message.topic.split('/')[1:]
        event = path[0]
        self.logger.debug("Event %s path: %s" % (event, repr(path[1:])))

        #self.exec_event(event, path[1:], message.payload)
        self.exec_event(event, message.topic, message.payload)
        pass

    def exec_event(self, name, path, payload):
        if hasattr(self, "event_"+name):
            handler = getattr(self, "event_"+name)
            handler(path, payload)
        pass

    @PatternMessageHandler('/photo', authorized=True)
    def cmd_photo(self):
        self.http_client.fetch("http://127.0.0.1:8082/0/action/snapshot")
        return True

    @PatternMessageHandler('/sub( .*)?', authorized=True)
    def cmd_sub(self, text):
        args = text.split()

        if len(args) < 1 or args[0].lower() != 'off':
            self.subscribe = True
        else:
            self.subscribe = False
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
        for sensor in self.sensors.values():
            self.notify_sensor(chat['id'], sensor)
        return True

    def notify_sensor(self, chat_id, sensor):
        self.bot.send_message(
            to=chat_id,
            message=self.sensor_template.render(sensor=sensor),
            parse_mode='HTML'
        )

    def event_camera(self, topic, payload):
        path = topic.split('/')
        event_type = path.pop()
        cam_no = path.pop()

        if event_type == 'photo':
            markup = None
            if not self.subscribe:
                markup = {
                        'inline_keyboard': [[{
                            'text': 'Subscribe',
                            'callback_data': '/sub'
                        }]]
                }

            for chat_id in self.bot.admins:
                self.bot.send_message(
                    to=chat_id,
                    message=Photo(
                        photo=File('image.jpg', StringIO(payload), 'image/jpeg'),
                        caption='camera#%s' % cam_no
                    ),
                    reply_markup=markup
                )
            return None

        if event_type == 'videom' or \
           (self.subscribe and event_type == 'video'):
            self.subscribe = False
            for chat_id in self.bot.admins:
                self.bot.send_message(
                    to=chat_id,
                    message=Video(
                        video=File('video.mp4', StringIO(payload), 'video/mp4')
                    )
                )
        pass

    def event_notify(self, topic, payload):
        self.logger.info("Event notify")
        for chat_id in self.bot.admins:
            self.bot.send_message(to=chat_id, message=payload)
        pass

    def event_sensor(self, topic, payload):
        status = int(payload)
        now = time.time()

        sensor = self.sensors[topic]
        sensor.state = status

        if status > 0 and (now-sensor.changed) > self.event_gap:
            sensor.changed = now
            if not sensor.silence:
                for chat_id in self.bot.admins:
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
    status.add_argument("--sensors", nargs="*", help="Sensor in format mqtt_topic:name[?]")
    status.add_argument("--cameras", nargs="*", help="Notify state of this camera")

    args = parser.parse_args()

    # configure logging
    logging.basicConfig(
        format="[%(asctime)s]\t[%(levelname)s]\t[%(name)s]\t%(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
        filename=args.logfile
    )
    logging.info("Starting telegram bot")
    ioloop = IOLoop.instance()

    handler = HomeBotHandler(
        ioloop,
        args.url,
        sensors=args.sensors,
        cameras=args.cameras
    )
    bot = Bot(args.token, args.admins, proxy=args.proxy, ioloop=ioloop)
    # Default handler
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
