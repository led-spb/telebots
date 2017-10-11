#!/usr/bin/python
# -*- coding: utf-8 -*-

import os, os.path, logging
import sys, argparse
import time, json
import urlparse
from telebot import Bot, BotRequestHandler
import requests
import re
import hashlib
import lxml.cssselect
import lxml.html


class UpdateScheduler():
   def __init__(self, handler):
       self.games = []
       self.events = []
       self.handler = handler
       handler.add_scheduler( self )

   def add_game(self, game ):
       if game['id'] in self.games:
          return False
       self.games.append( game['id'] )
       return True

   def clear(self):
       self.games = []

   def process_updates(self):
       to_remove = []

       handler.update_games_list()
       for id in self.games:
           game = handler.get_game(id)

           if game['link']==None:
              continue

           state,events = handler.parse_game_events( game['link'] )
           if state.lower()==u'матч завершен':
              to_remove.append( game )
              pass

           for event in events:
               hash = hashlib.md5()
               hash.update( ("%d_%s_%s" % (id, event['event_time'], event['event_text'] )).encode('utf-8') )
               h = hash.hexdigest()

               if h in self.events:
                  continue

               self.events.append(h)
               self.handler.bot.exec_event('match_event', event )

       for game in to_remove:
           self.handler.bot.exec_event( 'match_event', {'event_time':'', 'event_text':'Stop watching %s' % game['title'] } )
           self.games.remove( game['id'] )
       pass


class KHLBotHandler(BotRequestHandler):

   def __init__(self):
       self.logger = logging.getLogger(self.__class__.__name__)
       self.games = None
       self.scheduler = None
       self.last_updated = 0
       self.update_games_list()
       pass

   def add_scheduler(self, scheduler):
       self.scheduler = scheduler

   def __parse_game_info(self, item ):
       title = item.cssselect('.list-group-item-heading')[0].text_content()
       id = int(title.split(".")[0])
       name = title.split(".")[1].strip()
       link = None
       if item.attrib["href"] != '#':
          link  = "http://m.khl.ru/online/"+item.attrib["href"]
       state = item.cssselect('.list-group-item-text')[0].text_content().strip()
       return { 'id': id, 'title': name, 'link': link, 'state': state }

   def __parse_game_event(self, item):
       event_time = None
       sel = item.cssselect('.col-md-1')
       if len(sel)>0:
          event_time = sel[0].text_content().strip()
       events = [ x.text_content().strip() for x in item.cssselect("p") ]

       return {'event_time': event_time, 'event_text': "\n".join(events) }


   def parse_game_events(self, url):
       page = requests.get(url).text

       tree = lxml.html.fromstring( page )

       sel = lxml.cssselect.CSSSelector(u".lead" )
       state = ''
       for item in sel(tree):
          state = item.text_content().strip()

       sel = lxml.cssselect.CSSSelector( u"#tab-game .list-group-item" )

       events = [ self.__parse_game_event(item) for item in sel(tree) ]
       return (state, list(reversed(events)))


   def parse_games(self):
       url="http://m.khl.ru/online"
       page = requests.get(url).text

       tree = lxml.html.fromstring( page )
       sel = lxml.cssselect.CSSSelector( u"h4:contains('КХЛ') + div > .list-group-item" )

       games = [ self.__parse_game_info(item) for item in sel(tree) ]
       return games


   def get_game(self, id):
       for game in self.games:
           if game['id'] == int(id):
              return game
       return None


   def update_games_list(self):
       if time.time()-self.last_updated > 10*60:
          self.games = self.parse_games()
          self.last_updated = time.time()


   def cmd_game(self, game=None):
       if game==None or self.games==None:
          self.update_games_list()

          buttons = [ {'callback_data':'/game '+str(game['id']), 'text': game['title'] } for game in self.games ]
          keyboard = [ [x] for x in buttons ]
          return { 'text': "Which game?", 'markup': { 'inline_keyboard': keyboard } }
       else:
          for item in self.games:
             #logging.info( item['id'] )
             if item['id'] == int(game):
                res = self.scheduler.add_game( item )
                return { 'text': 'Begin watching game %s' % item['title'] if res else 'Game %s already watched' % item['title'] }
       return { 'text': 'Can\'t find this game' }
       pass


   def cmd_stop(self):
       self.scheduler.clear()
       return { 'text': 'Stop watching all games' }


   def event_match_event(self, event ):
       text = ""
       if event['event_time']!=None and event['event_time']!="":
          text = "%s: " % event['event_time']
       return { 'text': text+event['event_text'] }

   pass


if __name__ == '__main__':
    logging.getLogger("requests").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    class LoadFromFile( argparse.Action ):
        def __call__(self, parser, namespace, values, option_string = None):
           with values as f:
               parser.parse_args(f.read().split(), namespace)

    parser = argparse.ArgumentParser()
    parser.add_argument( "-c", "--config", type=open, action=LoadFromFile, help="Load config from file" )
    parser.add_argument( "--token",   help="Telegram API bot token" )
    parser.add_argument( "--admin",   nargs="+", help="Bot admin", type=int, dest="admins" )
    parser.add_argument( "-v", action="store_true", default=False, help="Verbose logging", dest="verbose" )
    parser.add_argument( "--logfile", help="Logging into file" )
    args = parser.parse_args()

    # configure logging
    logging.basicConfig( format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",  level=logging.DEBUG if args.verbose else logging.INFO, filename=args.logfile )
    logging.info("Starting khl bot")

    handler = KHLBotHandler()
    scheduler = UpdateScheduler(handler)
    bot     = Bot( args.token, args.admins, handler)

    bot.loop_start()
    try:
      while True:
        scheduler.process_updates()
        time.sleep(60)
    finally:
      bot.loop_stop()
