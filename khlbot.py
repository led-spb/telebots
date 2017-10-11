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



class Game:
   def __init__(self, element):
       self.logger = logging.getLogger(self.__class__.__name__)
       self.__parse_page_info(element)
       self.events = []
       self.last_updated = None

   def __str__(self):
       return ("game %d %s state %s link %s" % (self.id,  self.name, self.state, str(self.link))).encode('utf-8')

   def __parse_page_info(self, element):
       title = element.cssselect('.list-group-item-heading')[0].text_content().strip()

       self.id = int(title.split(".")[0])
       self.name = title.split(".")[1].strip()
       self.link = None

       if element.attrib["href"] != '#':
          self.link  = "http://m.khl.ru/online/"+element.attrib["href"]

       self.state = element.cssselect('.list-group-item-text')[0].text_content().strip()


   def __parse_game_event(self, item):
       event_time = None
       sel = item.cssselect('.col-md-1')
       if len(sel)>0:
          event_time = sel[0].text_content().strip()
       events = [ x.text_content().strip() for x in item.cssselect("p") ]
       return {'event_time': event_time, 'event_text': "\n".join(events) }


   def update_events(self):
       if self.link==None:
          return []
       self.logger.debug('Begin events update for %s' % str(self) )

       page = requests.get(self.link).text
       tree = lxml.html.fromstring( page )

       sel = lxml.cssselect.CSSSelector(u".lead" )
       self.state = ''
       for item in sel(tree):
          self.state = item.text_content().strip()

       sel = lxml.cssselect.CSSSelector( u"#tab-game .list-group-item" )
       events = [ self.__parse_game_event(item) for item in sel(tree) ]
       result = []
       for event in events:
           md5 = hashlib.md5()
           md5.update( ("%s_%s" % (event['event_time'], event['event_text'] )).encode('utf-8') )
           hash = md5.hexdigest()

           if hash not in self.events:
              self.last_updated = time.time()
              self.events.append( hash )
              result.insert(0, event)
       return result



class UpdateScheduler():
   def __init__(self, handler):
       self.logger = logging.getLogger(self.__class__.__name__)

       self.games = []
       self.events = []
       self.handler = handler
       handler.add_scheduler( self )

   def add_game(self, game ):
       if game.id in self.games:
          return False
       self.games.append( game.id )
       return True

   def stop_game(self, game):
       if game.id not in self.games:
          return False
       self.games.remove( game.id )
       return True

   def clear(self):
       self.games = []


   def process_updates(self):
       to_remove = []
       now = time.time()

       handler.update_games_list()
       for id in self.games:
           game = handler.find_game(id)

           events = game.update_events()
           for event in events:
               self.handler.bot.exec_event('match_event', event )

           if game.last_updated!=None and (now-game.last_updated)>60*60:
              ro_remove.append( game )

       for game in to_remove:
           self.handler.bot.exec_event( 'match_event', {'event_time':'', 'event_text':'Stop watching %s' % game.name } )
           self.games.remove( game.id )
       pass


class KHLBotHandler(BotRequestHandler):

   def __init__(self):
       self.logger = logging.getLogger(self.__class__.__name__)
       self.games = []
       self.scheduler = None
       self.last_updated = 0
       self.update_games_list()
       pass

   def add_scheduler(self, scheduler):
       self.scheduler = scheduler


   def parse_game_list(self):
       url="http://m.khl.ru/online"
       page = requests.get(url).text
       tree = lxml.html.fromstring( page )
       sel = lxml.cssselect.CSSSelector( u"h4:contains('КХЛ') + div > .list-group-item" )
       #sel = lxml.cssselect.CSSSelector( u"h4 + div > .list-group-item" )
       return [ Game(element) for element in sel(tree) ]


   def find_game(self, id):
       for game in self.games:
           if game.id == int(id):
              return game
       return None


   def update_games_list(self):
       if time.time()-self.last_updated > 10*60:
          self.logger.debug('Begin game list update' )

          new_games = self.parse_game_list()
          self.last_updated = time.time()

          cur_game_id = [x.id for x in self.games]
          new_game_id = [x.id for x in new_games]

          # remove obsolete games 
          to_remove = [ x for x in self.games if x.id not in new_game_id ]
          for game in to_remove:
              self.logger.debug('Removing obsolete %s' % str(game) )
              self.sheduler.stop(game)
              self.games.remove( game )


          # add/update info for new games
          for game in new_games:
              x = self.find_game(game.id)
              if x==None:
                 self.logger.debug('New %s' % str(game) )
                 self.games.append(game)
              else:
                 x.link = game.link
                 self.logger.debug('Updated %s' % str(x) )
          pass

   def cmd_games(self):
       self.update_games_list()
       buttons = [ {'callback_data':'/watch '+str(game.id), 'text': game.name } for game in self.games ]
       keyboard = [ [x] for x in buttons ]
       return { 'text': "Which game?", 'markup': { 'inline_keyboard': keyboard } }

   def cmd_watch(self, id=None):
       if id==None:
          return { 'text': 'Need a game id' }
    
       game = self.find_game(id)
       if game != None:
           res = self.scheduler.add_game( game )
           return { 'text': 'Begin watching game %s' % game.name if res else 'Game %s already watched' % game.name }
       return { 'text': 'Can\'t find this game' }


   def cmd_stop(self, id=None):
       if id==None:
          self.scheduler.clear()
          return { 'text': 'Stop watching all games' }

       game = self.find_game(id)
       if game != None:
           res = self.scheduler.stop_game( game )
           return { 'text': 'Stop watching game %s' % game.name if res else 'Game %s is not watched' % game.name }
       return { 'text': 'Can\'t find this game' }


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

    handler   = KHLBotHandler()
    scheduler = UpdateScheduler(handler)
    bot       = Bot( args.token, args.admins, handler)

    bot.loop_start()
    try:
      while True:
        try:
           scheduler.process_updates()
        except Exception, e:
           logging.exception("Error while processing games updates")

        time.sleep(60)
    finally:
      bot.loop_stop()
