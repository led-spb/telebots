import os
import re
import logging
import argparse
import urlparse
import asyncmqtt.client as mqtt
import json
import datetime
import zlib
import gpxpy.gpx
import gpxpy.geo
from cStringIO import StringIO
from tornado import gen
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado.httpclient import AsyncHTTPClient
from asynctelebot.telebot import Bot, BotRequestHandler, PatternMessageHandler
from asynctelebot.entity import *
from jinja2 import Environment
import humanize
from collections import defaultdict


def json_serial(obj):
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError("Type %s is not serializable" % type(obj))


class CarMonitor(mqtt.TornadoMqttClient, BotRequestHandler):

    def __init__(self, ioloop, url, name, api_key=None):
        BotRequestHandler.__init__(self)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.url = url
        self.devices = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: None)))
        self.ioloop = ioloop
        self.name = name
        self.low_battery = (10, 15)
        self.api_key = api_key
        self.track2img = 'https://open.mapquestapi.com/staticmap/v4/getmap?key={api_key}&size=600,600&'\
                         'type=map&imagetype=png&declutter=true&shapeformat=cmp&shape={shape}&'\
                         'bestfit={lat_min},{lon_min},{lat_max},{lon_max}&scalebar=false&'\
                         'scenter={lat_start},{lon_start}&ecenter={lat_end},{lon_end}'
        self.client = AsyncHTTPClient()

        self.tz_offset = datetime.timedelta(hours=3)
        self.msg_expire_delta = datetime.timedelta(minutes=15)
        self.jinja = Environment()
        self.jinja.filters['human_date'] = self.human_date
        self.activity_check_interval = datetime.timedelta(seconds=323)

        self.activity_task = PeriodicCallback(self.activity_job, self.activity_check_interval.seconds*1000)
        self.activity_task.start()

        mqtt.TornadoMqttClient.__init__(
            self, ioloop=ioloop, host=url.hostname, port=url.port if url.port is not None else 1883,
            username=url.username, password=url.password
        )
        pass

    @staticmethod
    def human_date(value):
        return humanize.naturaltime(value)

    @gen.coroutine
    def activity_job(self):
        self.logger.debug("Activity check job started")
        chat_id = self.bot.admins[0]
        try:
            for device in self.devices:
                status = self.devices[device]['status']
                if 'location_date' in status:
                    is_signal_lost = (datetime.datetime.now()-status['location_date']).total_seconds() >= 25*60*60
                    prev_signal_lost = status['lost'] or False
                    if is_signal_lost:
                        if not prev_signal_lost:
                            msg = '<b>WARN</b> last message from %s is %s' % \
                                  (device, self.human_date(status['location_date']))
                            self.logger.warn(msg)

                            yield self.bot.send_message(to=chat_id, message=msg, parse_mode='HTML')
                            yield self.notify_info(chat_id, device)
                            yield self.notify_location(chat_id, device)
                    else:
                        if prev_signal_lost:
                            msg = '<b>NORM</b> signal from %s is cached now' % device
                            self.logger.warn(msg)
                            yield self.bot.send_message(to=chat_id, message=msg, parse_mode='HTML')
                            yield self.notify_info(chat_id, device)
                            yield self.notify_location(chat_id, device)

                    status['lost'] = is_signal_lost
                pass
        except Exception:
            self.logger.exception("Exception in activity job")
        return

    @PatternMessageHandler("/track( .*)?", authorized=True)
    def cmd_track(self, text, chat):
        cmd = text.split()

        @gen.coroutine
        def execute():
            has_file = False
            mask = ''
            if len(cmd) > 1:
                try:
                    os.stat(cmd[1])
                    has_file = True
                except:
                    mask = cmd[1]
                    pass

            if not has_file:
                files = sorted([x for x in os.listdir('.')
                                if re.match('.*%s.*\.gpx' % mask, x)], reverse=True)[:10]
                buttons = [[{
                    'callback_data': '/track '+fname,
                    'text': fname
                }] for fname in files]
                self.bot.send_message(
                    to=chat['id'],
                    message='which track?' if len(files) > 0 else 'No tracks',
                    reply_markup={'inline_keyboard': buttons}
                )
            else:
                image = yield self.gpx_to_image(cmd[1])
                # send image
                self.bot.send_message(
                    to=chat['id'],
                    message=Photo(
                        photo=('image.png', StringIO(image), 'image/png'),
                        caption=cmd[1]
                    )
                )
            return
        execute()
        return True

    @gen.coroutine
    def gpx_to_image(self, gpx_file):
        with open(gpx_file, "r") as infile:
            gpx = gpxpy.parse(infile)
            data = self.encode_track(gpx)
            data['api_key'] = self.api_key
            url = self.track2img.format(**data)
            logging.debug(url)

            response = yield self.client.fetch(url, raise_error=False)
            logging.debug("Response code: %d %s", response.code, response.reason)
            logging.debug("%s", str(response.headers))
            response.rethrow()
            raise gen.Return(response.body)
            pass

    @PatternMessageHandler("/debug", authorized=True)
    def cmd_debug(self, message=None):
        chat_id = message['chat']['id'] if message is not None else self.bot.admins[0]

        buf = StringIO(json.dumps(self.devices, indent=2, sort_keys=True, default=json_serial))
        self.bot.send_message(
            to=chat_id,
            message=Document(
                document=File('debug.txt', buf, 'text/plain'),
                caption='debug info'
            )
        )
        return True

    @PatternMessageHandler("/info( .*)?", authorized=True)
    def cmd_info(self, chat, text):
        params = text.split()
        device = params[1] if len(params) > 1 else None
        self.notify_info(chat['id'], device)
        return True

    def notify_info(self, chat_id, device=None):
        template = self.jinja.from_string("""
        {% for device, info in devices.iteritems() %}
        <b>{{device}}</b>
        power: {{info.location.batt}}%
        ignition: {{ 'on' if info.status.charge>0 else 'off' }}
        temperature: {{info.location.temp}}
        distance move: {{info.status.distance}}m
        last location: {{info.status.location_date | human_date }}
        signal: {{info.location.src}} {{info.location.sat}}

        {% endfor %}
        """)
        devices = {name: data for name, data in self.devices.iteritems() if device is None or name == device}
        return self.bot.send_message(
            to=chat_id,
            messsage=template.render(devices=devices),
            parse_mode='HTML'
        )

    @PatternMessageHandler("/location", authorized=True)
    def cmd_location(self, chat):
        self.notify_location(chat['id'])
        return True

    def notify_location(self, chat_id, device=None):
        futures = []
        for dev, data in self.devices.iteritems():
            if dev == device or device is None:
                futures.append(
                    self.bot.send_message(
                        to=chat_id,
                        message=Venue(
                            latitude=data['location']['lat'],
                            longitude=data['location']['lon'],
                            title=dev, address="Unknown"
                        )
                    )
                )
        return futures

    def on_mqtt_connect(self, client, userdata, flags, rc):
        self.logger.info("MQTT broker connection result: %s", mqtt.connack_string(rc))
        if rc == 0:
            client.subscribe("owntracks/%s/+" % self.name, 0)
        pass

    def update_status(self, device, payload):
        self.devices[device][payload['_type']].update(payload)

    def on_track(self, device, event_time, payload):
        filename = "%s-%s.gpx" % (device, event_time.strftime("%Y_%m_%d-%H_%M"))
        self.logger.info("Storing track to %s", filename)

        gpx = self.track_to_gpx(payload["track"])
        f = open(filename, "wb")
        f.write(gpx.to_xml())
        f.close()
        pass    

    def on_msg(self, device, event_time, payload):
        self.logger.info("Message from %s: %s", device, payload['text'])
        pass    

    def on_location(self, device, event_time, payload):
        self.logger.info("Location for %s received", device)
        chat_id = self.bot.admins[0]

        battery = payload['batt']

        last_charge = self.devices[device]['status']['charge'] or 0
        low_battery = self.devices[device]['status']['low_batt'] or False

        if battery <= self.low_battery[0] and not low_battery:
            low_battery = True
            msg = '<b>WARN</b> %s has low battery (%d%%)' % (device, battery)
            self.logger.warn(msg)
            self.bot.send_message(to=chat_id, message=msg, parse_mode='HTML')
        if battery >= self.low_battery[1] and low_battery:
            low_battery = False
            msg = '<b>NORM</b> %s has norm battery (%d%%)' % (device, battery)
            self.logger.info(msg)
            self.bot.send_message(to=chat_id, message=msg, parse_mode='HTML')

        if last_charge != payload['charge']:
            msg = 'Ignition changed to %s' % ('ON' if payload['charge'] > 0 else 'OFF')
            self.logger.warn(msg)
            pass

        last_location = None
        distance = 0
        if 'location' in self.devices[device]['status']:
            last_location = self.devices[device]['status']['location']
            distance = gpxpy.geo.distance(
                last_location[0], last_location[1], None, payload['lat'], payload['lon'], None
            )

        if distance > 500:
            self.notify_location(chat_id, device)

        self.devices[device]['status']['low_batt'] = low_battery
        self.devices[device]['status']['location_date'] = event_time
        self.devices[device]['status']['location'] = (payload['lat'], payload['lon'])
        self.devices[device]['status']['distance'] = distance
        self.devices[device]['status']['charge'] = payload['charge']
        pass

    def on_mqtt_message(self, client, userdata, message):
        try:
            sysdate = datetime.datetime.now()
            self.logger.debug("Got mqtt message on topic %s", message.topic)

            d = message.topic.split("/")
            device, tracker = (d[1], d[2])

            payload = {}
            try:
                payload = json.loads(message.payload)
            except:
                try:
                    # gzip.decompress(message.payload).decode("utf-8")
                    s = zlib.decompress(message.payload, 16+zlib.MAX_WBITS)
                    payload = json.loads(s)
                except:
                    self.logger.warn("unknown message compression type %s" % payload)
                    pass
             
            if '_type' in payload:
                event_time = None
                if 'tst' in payload:
                    event_time = datetime.datetime.utcfromtimestamp(payload['tst']) + self.tz_offset
                is_old = (sysdate-event_time) > self.msg_expire_delta

                self.logger.info("%s message from %s/%s at %s" % (payload['_type'], device, tracker, event_time))
                self.update_status(device, payload)

                callback_name = 'on_'+payload['_type']
                if hasattr(self, callback_name):
                    getattr(self, callback_name)(device, event_time, payload)

                logging.debug(json.dumps(self.devices, indent=2, sort_keys=True, default=json_serial))
                return
            self.logger.warn("unknown message type %s" % payload)
        except:
            self.logger.exception("error while processing MQTT message")
        return

    @staticmethod
    def track_to_gpx(track):
        gpx = gpxpy.gpx.GPX()
        gpx_track = gpxpy.gpx.GPXTrack()
        gpx.tracks.append(gpx_track)
        gpx_segment = gpxpy.gpx.GPXTrackSegment()
        gpx_track.segments.append(gpx_segment)

        for idx, p in enumerate(track):
            point = gpxpy.gpx.GPXTrackPoint(
                p["lat"], p["lon"],
                elevation=p['alt'] if 'alt' in p else None,
                time=datetime.datetime.utcfromtimestamp(p["tst"]),
                speed=p["vel"] if 'vel' in p else None,
                name="Start" if idx == 0 else ("Finish" if idx == len(track)-1 else None)
            )
            gpx_segment.points.append(point)
        return gpx

    @staticmethod
    def encode_track(gpx):
        def encode_number(num):
            num = num << 1
            if num < 0:
                num = ~num
            encoded = ''
            while num >= 0x20:
                encoded = encoded + chr((0x20 | (num & 0x1f)) + 63)
                num = num >> 5
            return encoded + chr(num + 63)

        namespace = {
            'lat_start': None,
            'lon_start': None,
            'lat_end': None,
            'lon_end': None,
            'lat_min': None,
            'lon_min': None,
            'lat_max': None,
            'lon_max': None
        }
        encoded = ''
        old_lat = 0
        old_lon = 0

        for tr in gpx.tracks:
            for seg in tr.segments:
                for p in seg.points:
                    if namespace['lat_min'] is None or namespace['lat_min'] > p.latitude:
                        namespace['lat_min'] = p.latitude
                    if namespace['lat_max'] is None or namespace['lat_max'] < p.latitude:
                        namespace['lat_max'] = p.latitude
                    if namespace['lon_min'] is None or namespace['lon_min'] > p.longitude:
                        namespace['lon_min'] = p.longitude
                    if namespace['lon_max'] is None or namespace['lon_max'] < p.longitude:
                        namespace['lon_max'] = p.longitude

                    if namespace['lat_start'] is None:
                        namespace['lat_start'] = p.latitude
                        namespace['lon_start'] = p.longitude

                    namespace['lat_end'] = p.latitude
                    namespace['lon_end'] = p.longitude

                    lat = int(p.latitude * 100000)
                    lon = int(p.longitude * 100000)
                    encoded = encoded + encode_number(lat - old_lat) + encode_number(lon - old_lon)
                    old_lat = lat
                    old_lon = lon
                    pass
        namespace['shape'] = encoded
        return namespace


def main():
    class LoadFromFile(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            with values as f:
                parser.parse_args(f.read().split(), namespace)

    parser = argparse.ArgumentParser(fromfile_prefix_chars='@')
    parser.add_argument("-c", "--config", type=open, action=LoadFromFile, help="Load config from file")
    parser.add_argument("-n", "--name", default="+")
    parser.add_argument("--token", help="Telegram API bot token")
    parser.add_argument("--key", help="MapQuest API key")
    parser.add_argument("--admin", nargs="+", help="Bot admin", type=int, dest="admins")
    parser.add_argument("-u", "--url", default="mqtt://localhost:1883", type=urlparse.urlparse)
    parser.add_argument("-v", action="store_true", default=False, help="Verbose logging", dest="verbose")
    parser.add_argument("--logfile", help="Logging into file")
    args = parser.parse_args()

    logging.basicConfig(
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
        filename=args.logfile
    )

    ioloop = IOLoop.instance()

    bot = Bot(args.token, args.admins)
    monitor = CarMonitor(ioloop, args.url, args.name, args.key)
    bot.add_handler(monitor)

    monitor.start()
    bot.loop_start()

    try:
        ioloop.start()
    except KeyboardInterrupt:
        ioloop.stop()
    finally:
        pass
    pass


if __name__ == "__main__":
    main()
