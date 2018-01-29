#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import argparse
import urlparse
from telebot import Bot, BotRequestHandler
import requests
#import cookielib
from datetime import datetime
import re
import sys
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
       if len(query)==0:
          return { 'text': 'Empty query' }
       results = self.do_search( " ".join(query) )
       res = [ self.format_item(item) for item in results ]
       return res if len(res)>0 else None


class DownloadHandler(BotRequestHandler):
   def __init__(self, helpers=[], target=".", proxy=None):
       self.logger  = logging.getLogger(self.__class__.__name__)
       self.helpers = helpers
       self.proxy   = proxy
       self.target_path = target

   def getCommand(self, name):
       return self.cmd_download

   def cmd_download(self, full_message):
       urls = re.findall('https?://\S+', full_message)
       if len(urls)==0:
          return
       url = urls[0]
       for helper in self.helpers:
           if helper.__class__.check_url(url):
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
       return {'text': 'Url "%s" is unknown' %url }



if __name__ == '__main__':
    import download_helpers

    logging.getLogger("requests").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)

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
    actions.add_argument( "action", choices=["notify","serve"], nargs="?", default='serve' )


    args = parser.parse_args()

    # configure logging
    bot     = Bot( args.token, args.admins )
    if args.action=='notify':
       message = sys.stdin.read()
       for user in args.admins:
           bot.send_message( to=user, text=message )
       exit()

    logging.basicConfig( format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",  level=logging.DEBUG if args.verbose else logging.INFO, filename=args.logfile )
    logging.info("Starting torrent bot")

    # Torrent search handler
    bot.addHandler( NnmSearchHandler() )

    # Torrent download handler
    helpers = []
    for url in args.helper:
        helper = download_helpers.create_helper(url)
        if helper!=None:
           helpers.append(helper)
        else:
           logging.warn( "%s is unknown helper", url)
    bot.addHandler( DownloadHandler(helpers=helpers, target=args.download_dir, proxy=args.proxy) )

    try:
      bot.loop_forever()
    finally:
      pass