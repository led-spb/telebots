#!/usr/bin/python
# -*- coding: utf-8 -*-

import os, os.path, logging
import sys, argparse
import time, json
import urlparse
from telebot import Bot, BotRequestHandler
import paho.mqtt.client as mqtt
from cStringIO import StringIO
import requests
from datetime import datetime
import re


class HomeBotHandler(BotRequestHandler):
   def __init__(self, mqtt_url, sensors=None, cameras=None ):
       self.logger = logging.getLogger(self.__class__.__name__)
       self.sensors = sensors or []
       self.cameras = cameras or []
       self.event_gap = 300
       self.events = {}

       host = mqtt_url.hostname
       port = mqtt_url.port if mqtt_url!=None else 1883

       self.logger.info("Trying connect to MQTT broker at %s:%d" % (host, port) )

       self.mqttc = mqtt.Client()
       if mqtt_url.username!=None:
          self.mqttc.username_pw_set( mqtt_url.username, mqtt_url.password )

       self.mqttc.on_connect = self._on_connect
       self.mqttc.on_message = self._on_message
       self.mqttc.connect( host, port, 60 )
       #self.mqttc.loop_start()
       self.subscribe = False
       pass

   def _on_connect( self, client, obj, flags, rc ):
       self.logger.info("MQTT broker: %s", mqtt.connack_string(rc) )
       if rc==0:
          topics = ["/home/notify"] + ["/home/sensor/%s" % x for x in self.sensors ] + ["/home/camera/%s/#" % x for x in self.cameras]
          for topic in topics:
              self.logger.debug("Subscribe for topic %s" % topic)
              self.mqttc.subscribe( topic )
       pass

   def _on_message( self, mosq, obj, msg ):
       if msg.retain:
          return

       self.logger.info("topic %s, payload: %s" % (msg.topic, "[binary]" if len(msg.payload)>10 else msg.payload) )
       path = msg.topic.split('/')[2:]
       event = path[0]
       self.logger.debug("Event %s path: %s" % (event, repr(path[1:])) )
       self.bot.exec_event( event, path[1:], msg.payload )
       pass

   def cmd_photo(self):
       requests.get("http://127.0.0.1:8082/0/action/snapshot")
       return None

   def cmd_sub(self, *args):
       if len(args)<1 or args[0].lower()!='off':
          self.subscribe = True
       else:
          self.subscribe = False
       return None

   def cmd_stat(self, *args):
       template = '{% for item in states.sensor %}{% if item.state!=\'unknown\' %}{{ item.name }} is {{item.state_with_unit}}\n{% endif %}{% endfor %}'
       return requests.post('http://127.0.0.1:8123/api/template', data=json.dumps({'template': template}) ).text

   def cmd_video(self, video=None):
       if video is None:
          files = sorted( [x for x in os.listdir('/home/hub/motion') if re.match('\d{8}_\d{6}\.mp4',x) ], reverse=True )
          buttons = [ {'callback_data':'/video '+fname, 'text': re.sub('^\d{8}_(\d{2})(\d{2}).*$', '\\1:\\2', fname) } for fname in files ]
          keyboard = [ x for x in [ buttons[i*7:(i+1)*7] for i in range(len(buttons)/7+1) ] if len(x)>0 ]
          return { 'text': "which video?", 'markup': { 'inline_keyboard': keyboard } }

       caption = re.sub('^\d{8}_(\d{2})(\d{2}).*$', '\\1:\\2', video)
       return { 'video': ( 'video.mp4', open('/home/hub/motion/'+video,'rb'), 'video/mp4'), 'extra': { 'caption': caption } }


   def event_camera(self, path, payload ):
       cam_no = path[0]
       event_type = path[1]

       if event_type=='photo':
          response = { 'photo': ('image.jpg', StringIO(payload),'image/jpeg'),  'extra': { 'caption': 'camera#%s' % cam_no } }
          if not self.subscribe:
             response.update( {'markup': {'inline_keyboard': [ [{'text':'Subscribe', 'callback_data':'/sub'}]] } } )
          return response

       if event_type=='videom' or (self.subscribe and event_type=='video'):
          self.subscribe = False
          return { 'video': ('video.mp4', StringIO(payload), 'video/mp4') }

       return None

   def event_notify(self, path, payload ):
       return payload

   def event_sensor(self, path, payload ):
       sensor = path[0]
       value = payload
       now = time.time()

       if int(value)>0 and (sensor not in self.events or (now-self.events[sensor])>self.event_gap):
          self.events[sensor] = now
          return "%s: alert %s" % ( sensor, time.strftime("%d.%m %H:%M") )
       return None
   pass


if __name__ == '__main__':
    logging.getLogger("requests").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    class LoadFromFile( argparse.Action ):
        def __call__(self, parser, namespace, values, option_string = None):
           with values as f:
               parser.parse_args(f.read().split(), namespace)

    parser = argparse.ArgumentParser(fromfile_prefix_chars='@')

    basic = parser.add_argument_group('basic','Basic parameters')
    basic.add_argument( "-c", "--config", type=open, action=LoadFromFile, help="Load config from file" )
    basic.add_argument( "-u","--url", default="localhost:1883", type=urlparse.urlparse, help="MQTT Broker address host:port"  )
    basic.add_argument( "--token",   help="Telegram API bot token" )
    basic.add_argument( "--admin",   nargs="+", help="Bot admin", type=int, dest="admins" )
    basic.add_argument( "--logfile", help="Logging into file" )
    basic.add_argument( "-v", action="store_true", default=False, help="Verbose logging", dest="verbose" )

    status = parser.add_argument_group('status', 'Home state parameters')
    status.add_argument( "--sensors", nargs="*", help="Notify state of this sensors", type=str)
    status.add_argument( "--cameras", nargs="*", help="Notify state of this camera", type=str)

    args = parser.parse_args()

    # configure logging
    logging.basicConfig( format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",  level=logging.DEBUG if args.verbose else logging.INFO, filename=args.logfile )
    logging.info("Starting telegram bot")

    handler = HomeBotHandler( args.url, sensors=args.sensors, cameras=args.cameras )
    bot     = Bot( args.token, args.admins )

    # Default handler
    bot.addHandler( handler )

    bot.loop_start()
    try:
      handler.mqttc.loop_forever()
    finally:
      handler.mqttc.loop_stop()
      bot.loop_stop()
