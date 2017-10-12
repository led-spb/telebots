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
import cookielib
from datetime import datetime
import re
import lxml.cssselect
import lxml.html


class NnmSearchHandler(BotRequestHandler):
   def __init__(self):
       self.logger = logging.getLogger(self.__class__.__name__)
       pass

   def do_search(self, query):
       url = "http://nnm-club.name/forum/tracker.php"
       r = requests.post(url, data={
             'nm': query.encode('windows-1251'), 
             'submit': (u'Поиск').encode('windows-1251'),
       })
       tree = lxml.html.fromstring( r.text )

       sel = lxml.cssselect.CSSSelector(u"table.forumline.tablesorter tr.prow1,tr.prow2" )
       results = []
       for item in sel(tree):
          results.append( self.parse_result(item) )
       return results
       pass

   def parse_result(self, element):
       cells = element.cssselect('td')
       return {'title': cells[2].text_content().strip(), 
               'link': 'http://nnm-club.name/forum/'+cells[2].cssselect('a')[0].attrib['href'],
               'category': cells[1].text_content().strip(),
               'size': int(cells[5].cssselect('u')[0].text_content().strip()),
               'added': int(cells[9].cssselect('u')[0].text_content().strip())
       }

   def format_item(self, item):
       message = u"<b>%s</b>\nРаздел: %s\nРазмер: %s\nДобавлено: %s\n%s" % (item['title'], item['category'], self.format_size(item['size']), self.format_time(item['added']), item['link'])
       buttons = [ {'callback_data': '/download %s' % item['link'], 'text': 'Download' } ]
       return { 'text': message, 'markup': { 'inline_keyboard': [ buttons ] }, 'extra': {'parse_mode':'html', 'disable_notification': True, 'disable_web_page_preview': False} }

   def format_time(self, tm ):
       return datetime.fromtimestamp(tm).strftime("%d.%m.%Y %H:%M")
   
   def format_size(self, size):
       size=int(size)
       if size>1024*1024*1024:
          return "%.2f GB" % ( int(size) / (1024.0*1024*1024) )
       if size>1024*1024:
          return "%.2f MB" % ( int(size) / (1024.0*1024) )
       if size>1024:
          return "%.2f KB" % ( int(size) / (1024.0) )
       return "%d B" % size

   def cmd_nnm(self, *query):
       results = self.do_search( " ".join(query) )
       res = [ self.format_item(item) for item in results ]
       return res if len(res)>0 else None



class HomeBotHandler(BotRequestHandler):
   def __init__(self, mqtt_url ):
       self.logger = logging.getLogger(self.__class__.__name__)

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
          self.mqttc.subscribe("/home/alarm/#")
       pass

   def _on_message( self, mosq, obj, msg ):
       if msg.retain:
          return
       self.logger.info("topic %s, payload: %s" % (msg.topic, "[binary]" if len(msg.payload)>10 else msg.payload) )
       path = msg.topic.split('/')[3:]
       event = path[0]
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
       if sensor=='door':
          if int(value)>0:
             return "%s: alert %s" % ( sensor, time.strftime("%d.%m %H:%M") )
       return None
   pass


from download_helpers import DownloadHelper, NnmClubDownloadHelper

class DownloadHandler(BotRequestHandler):
   def __init__(self):
       self.logger  = logging.getLogger(self.__class__.__name__)
       self.helpers = [ NnmClubDownloadHelper('led_spb','fiwrqq') ]
       self.proxy   = 'socks5://192.168.168.2:9050'
       self.target_path = '/home/pi/Downloads'

   def cmd_download(self, url):    
       for helper in self.helpers:
           if helper.check_url(url):
              try:
                 try:
                    filename = helper.download( url, self.target_path )
                    return {'text': 'Downloaded to %s' %filename }
                 except Exception,e:
                    if self.proxy==None:
                       raise e

                    logging.info("Trying to use tor proxy. Cause %s: %s" % ( e.__class__.__name__, str(e) ) )
                    helper.session.proxies = { 'http': self.proxy, 'https': self.proxy }
                    helper.isAuth=None
                    helper.login()
                    filename = helper.download( url, self.target_path )

                    return {'text': 'Downloaded to %s' %filename }
                 finally:
                    helper.session.proxies = None
              except Exception,e:
                 raise e
       return {'text': 'Url is unknown' %url }


if __name__ == '__main__':
    logging.getLogger("requests").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    class LoadFromFile( argparse.Action ):
        def __call__(self, parser, namespace, values, option_string = None):
           with values as f:
               parser.parse_args(f.read().split(), namespace)

    parser = argparse.ArgumentParser()
    parser.add_argument( "-c", "--config", type=open, action=LoadFromFile, help="Load config from file" )
    parser.add_argument( "-u","--url", default="localhost:1883", type=urlparse.urlparse, help="MQTT Broker address host:port"  )
    parser.add_argument( "--token",   help="Telegram API bot token" )
    parser.add_argument( "--admin",   nargs="+", help="Bot admin", type=int, dest="admins" )
    parser.add_argument( "-v", action="store_true", default=False, help="Verbose logging", dest="verbose" )
    parser.add_argument( "--logfile", help="Logging into file" )
    args = parser.parse_args()

    # configure logging
    logging.basicConfig( format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",  level=logging.DEBUG if args.verbose else logging.INFO, filename=args.logfile )
    logging.info("Starting telegram bot")

    handler = HomeBotHandler( args.url )
    bot     = Bot( args.token, args.admins )

    bot.addHandler( handler )
    bot.addHandler( NnmSearchHandler() )
    bot.addHandler( DownloadHandler() )

    bot.loop_start()
    try:
      handler.mqttc.loop_forever()
    finally:
      handler.mqttc.loop_stop()
      bot.loop_stop()
