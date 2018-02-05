#!/usr/bin/python
# -*- coding: utf-8 -*-
import logging
import argparse
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, MessageHandler, Filters, CallbackQueryHandler
import json
import time
from datetime import datetime
import re, os.path
import traceback
import sys
from jinja2 import Environment, Template
import urlparse


class ItemRenderer:
   def __init__(self):
       self.jinja2 = Environment()
       self.jinja2.filters['datetimeformat'] = self._datetimeformat
       self.jinja2.filters['todatetime'] = self._todatetime # {% if item.size | default(0) | number %}{{item.size | default(0) | int | filesizeformat}}{% else %}{{item.size | e}}{% endif %}
       self.template = self.jinja2.from_string(
u"""<b>{{item.title|e}}</b>
Раздел: {{item.category|e}}
Размер: {% if item.size | int(-1) == -1 %}{{item.size | e}}{% else %}{{ item.size | default(0) | int | filesizeformat }}{% endif %}
Добавлено: {{ item.added | default(0) | int | todatetime | datetimeformat('%d-%m-%Y') }}
Скачать: /download{{item.id}}

""")

   def _datetimeformat(self, value, format='%d-%m-%Y %H:%M:%s'):
       return value.strftime(format)

   def _todatetime(self, value):
       return datetime.fromtimestamp( int(value) )
        
   def render(self, item):
       return self.template.render( item = item)


class RequestHandler:

   def __init__(self, updater, target_path, admins, helpers):
       self.admins  = admins
       self.target_path = target_path
       self.updater = updater
       self.helpers = helpers
       self.results = {}

       self.renderer = ItemRenderer()

       updater.dispatcher.add_handler( MessageHandler( Filters.text, self.on_message ) )
       updater.dispatcher.add_handler( CallbackQueryHandler( self.on_callback ) )
       updater.dispatcher.add_handler( MessageHandler( Filters.command, self.on_command ) )
       pass

   def on_callback(self, bot, update):
       if (update.effective_user is None) or (update.effective_user.id not in self.admins):
          return
       message_id = update.callback_query.message.message_id
       user_id = update.effective_user.id

       pos = update.callback_query.data
       logging.info("On callback %s from %s " % (update.callback_query.data, update.effective_user.id))
       if user_id in self.results:
          self.show_results(bot, user_id, message_id, self.results[user_id], int(pos) )

   def on_command(self, bot, update):
       if (update.effective_user is None) or (update.effective_user.id not in self.admins):
           return

       message_id = update.effective_message.message_id
       user_id = update.effective_user.id
       item_id = re.search( '^\/download(.*)$', update.effective_message.text )

       if user_id in self.results and item_id!=None:
          item_id = item_id.group(1)
          for item in self.results[user_id]:
              if item.id == item_id:
                 self.on_url( bot, user_id, message_id, item.link )
                 return
       pass

   def on_url(self, bot, user_id, message_id, url):
       logging.info( 'Processing url "%s" from %s' % (url, user_id) )
       message = bot.sendMessage( chat_id=user_id, text='Downloading...' )
       message_id = message.message_id
       try:
         for helper in self.helpers:
             if helper.__class__.check_url(url):
                logging.info( helper.proxy )
                filename = helper.download( url, self.target_path )
                bot.editMessageText( chat_id=user_id, message_id=message_id, text='Downloaded to %s' % (filename) )
                return
       except:
         logging.exception('Error while downloading url')
         error_text = traceback.format_exc()
         bot.editMessageText( chat_id=user_id, message_id=message_id, text='Sorry, error occured!\n%s' % error_text )
       pass

   def on_message(self, bot, update):
       if (update.effective_user is None) or (update.effective_user.id not in self.admins):
           return

       user_id    = update.effective_user.id
       message_id = update.effective_message.message_id

       url = re.search("https?://\\S+", update.effective_message.text)
       if url !=None:
          self.on_url(bot, user_id, message_id, url.group(0) )
          return

       logging.info( 'Processing query request "%s" from %s' % (update.effective_message.text, update.effective_user.id) )
       message = bot.sendMessage( chat_id=user_id, text='Searching...' )
       message_id = message.message_id
       query_string = update.effective_message.text

       result = []
       error_text = None

       for helper in self.helpers:
           try:
              logging.info("Searching %s by %s" % (query_string, helper.__class__.__name__) )
              data = helper.do_search( query_string )
              logging.info("Found %d items" % len(data) )
              result += data
           except:
              logging.exception("Error while search")
              error_text = traceback.format_exc()
              bot.editMessageText( chat_id=user_id, message_id=message_id, text='Sorry, error occured!\n%s' % error_text )

       self.results[ update.effective_user.id ] = result
       if len(result)==0 and error_text==None:
          bot.editMessageText( chat_id=user_id, message_id=message_id, text='Sorry, nothing is found' )
          return

       self.show_results( bot, user_id, message_id, result )
       pass

   def show_results(self, bot, chat_id, message_id, results, start=1, page_size=3):
       data = map( (lambda i: self.renderer.render(results[i]) ), range( start-1, min( start+page_size-1, len(results)) ) )
       message = u"\n".join(data)
       logging.debug(message)
       bot.editMessageText( chat_id=chat_id, message_id=message_id, text=message, parse_mode='HTML' )

       buttons=[]
       if start>page_size:
          buttons.append( InlineKeyboardButton(text="Prev %d" % page_size,callback_data = str(start-page_size) ) )
       if (start+page_size) < len(results):
          buttons.append( InlineKeyboardButton(text="Next %d" % page_size,callback_data = str(start+page_size) ) )
       if len(buttons)>0:
          bot.editMessageReplyMarkup( chat_id=chat_id, message_id=message_id, reply_markup = InlineKeyboardMarkup( inline_keyboard=[buttons] ) )
       return


def create_helper(url):
    p = urlparse.urlparse(url)
    baseurl = "%s://%s/" % (p[0],p.hostname)
    username = p.username
    password = p.password

    for cls in download_helpers.DownloadHelper.__subclasses__():
        if cls.check_url(baseurl):
            return cls(username, password)
    return None


if __name__ == '__main__':
    import download_helpers

    class LoadFromFile( argparse.Action ):
        def __call__(self, parser, namespace, values, option_string = None):
           with values as f:
               parser.parse_args(f.read().split(), namespace)

    parser = argparse.ArgumentParser(fromfile_prefix_chars='@')

    basic = parser.add_argument_group('basic','Basic parameters')
    basic.add_argument( "-c", "--config", type=open, action=LoadFromFile, help="Load config from file" )
    basic.add_argument( "--token",   help="Telegram API bot token" )
    basic.add_argument( "--admin",   nargs="+", help="Bot admin", type=int, dest="admins" )
    basic.add_argument( "--logfile", help="Logging into file" )
    basic.add_argument( "-v", action="store_true", default=False, help="Verbose logging", dest="verbose" )

    download = parser.add_argument_group('download', 'Download helper parameters')
    download.add_argument( "--helper",  nargs="*" )
    download.add_argument( "--download-dir", dest="download_dir", default="." )
    download.add_argument( "--proxy" )

    actions = parser.add_argument_group('action', 'Action arguments')
    actions.add_argument( "action", choices=["notify","serve","query"], nargs="?", default='serve' )


    args = parser.parse_args()

    logging.getLogger("requests").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    logging.basicConfig( format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",  level=logging.DEBUG if args.verbose else logging.INFO, filename=args.logfile )

    # Torrent download handler
    helpers = []
    for url in args.helper:
        helper = create_helper(url)
        if helper!=None:
           helper.proxy = args.proxy
           helpers.append(helper)
           logging.info( helper.proxy )
        else:
           logging.warn( "%s is unknown helper", url)

    logging.info("Starting torrent bot, helpers: [%s] " % ",".join( [x.__class__.__name__ for x in helpers] ) )
    updater = Updater( args.token )
    handler = RequestHandler( updater, args.download_dir, args.admins, helpers )

    updater.start_polling( timeout=60 )
    updater.idle()
