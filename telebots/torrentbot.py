#!/usr/bin/python
# -*- coding: utf-8 -*-
import re
import sys
import os
import requests
import cookielib
import argparse
import shutil
import hashlib
import json
import bencode
import logging
import base64
import bencode
import lxml.cssselect
import lxml.html
import urllib
import traceback
from datetime import datetime
from urlparse import urlparse

from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado import gen
from telebot import Bot, BotRequestHandler, authorized
from jinja2 import Environment, Template


class ItemRenderer:
   def __init__(self):
       self.jinja2 = Environment()
       self.jinja2.filters['datetimeformat'] = self._datetimeformat
       self.jinja2.filters['todatetime'] = self._todatetime
       self.template = self.jinja2.from_string(
u"""<b>{{item.title|e}}</b>
Раздел: {{item.category|e}}
Размер: {% if item.size | int(-1) == -1 %}{{item.size | e}}{% else %}{{ item.size | default(0) | int | filesizeformat }}{% endif %}
Добавлено: {{ item.added | default(0) | int | todatetime | datetimeformat('%d-%m-%Y') }}
Скачать: /download_{{item.id}}

""")

   def _datetimeformat(self, value, format='%d-%m-%Y %H:%M:%s'):
       return value.strftime(format)

   def _todatetime(self, value):
       return datetime.fromtimestamp( int(value) )
        
   def render(self, item):
       return self.template.render( item = item)


class ResultItem:
    __attributes__ = ['id', 'title', 'category', 'link', 'added', 'size']

    def __init__(self, **kwargs ):
        self.__data__ = kwargs
        pass

    def __getattr__(self, item):
        if item in self.__class__.__attributes__:
            return self.__data__[item] if item in self.__data__ else None
        return None

    def __str__(self):
        return json.dumps(self.__data__)


class TrackerHelper(object):
    timeout = 10
    torrent_path = "."
    cookies = cookielib.CookieJar()

    @staticmethod
    def init(cookie, timeout, path):
        TrackerHelper.cookies = cookielib.MozillaCookieJar( cookie )
        try:
            TrackerHelper.cookies.load( ignore_discard=True, ignore_expires=True )
        except Exception,e:
            pass
        TrackerHelper.timeout = timeout
        TrackerHelper.torrent_path = path
        return

    @staticmethod
    def finish():
        try:
            TrackerHelper.cookies.save( ignore_discard=True, ignore_expires=True )
        except Exception, e:
            pass
        return

    @staticmethod
    def subclass_for(url):
        res = urlparse(url)
        for subclass in TrackerHelper.__subclasses__():
            names = subclass.name if isinstance(subclass.name, list) else [subclass.name]
            if res.hostname in names:
                return subclass
        return None

    def __init__(self, url, proxy=None):
        res = urlparse(url)
        self.user     = res.username
        self.passwd   = res.password
        self.base_url = "%s://%s/" % (res.scheme, res.hostname)

        self.session = requests.Session()
        self.session.cookies = TrackerHelper.cookies
        self.session.headers = {
              'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/29.0.1547.66 Safari/537.36',
              'Accept-Charset': 'utf-8'
        }
        if proxy!=None:
            self.session.proxies = {'http': proxy}

    def login(self):
        pass

    def check_url(self, url):
        return re.search("^%s" % self.base_url, url) != None

    def download(self, url):
        pass

    def do_search(self, query):
        pass


class Noname_club(TrackerHelper):
    name   = ["nnm-club.me", "nnmclub.to"]

    def __init__(self, url, proxy ):
        TrackerHelper.__init__(self, url, proxy )
        self.isAuth = False
        self.sid = None
        self.client = AsyncHTTPClient()
        pass

    def check_auth( self, body):
        #f = open("login.dat","w")
        #f.write(body)
        #f.close()
        m = re.search( '<a\s+href="login\.php\?logout=true&amp;sid=(.*?)"', body, re.I+re.M )
        status = False
        if m is not None:
            self.sid = m.group(1)
            status = True

        logging.debug("Noname-club auth status %s, sid=%s", "ok" if status else "fail", self.sid)
        return status

    @gen.coroutine
    def login(self):
        if self.isAuth:
            return
        url = '%sforum/login.php' % self.base_url
        logging.info("Initial connect to %s", self.base_url)
        request = HTTPRequest(
            url,
            headers = self.session.headers,
            method = 'GET',
            connect_timeout=5, request_timeout=20
        )
        response = yield self.client.fetch(request, raise_error = False)
        logging.info("Response code: %d %s", response.code, response.reason)
        logging.debug("%s", str(response.headers))
        response.rethrow()

        m = re.search('<form.*?action="login.php".*?>(.*?)</form>', response.body, re.I+re.M+re.U+re.S)
        form = m.group(1)
        login_data = { 
           'login': u'Вход'.encode('windows-1251'),
           'username': self.user, 'password': self.passwd,
           'autologin':'on' 
        }
        for m in re.finditer(r'<input\s+type="hidden"\s+name="(.*?)"\s+value="(.*?)"', form, re.I+re.M+re.S ):
            login_data[ m.group(1) ] = m.group(2)

        request = HTTPRequest(
            url, headers=self.session.headers , method='POST', body=urllib.urlencode(login_data),
            connect_timeout=5, request_timeout=60
        )
        logging.info("Passing credentinals to %s", self.base_url)
        response = yield self.client.fetch( request, raise_error = False )
        logging.info("Response code: %d %s", response.code, response.reason)

        response.rethrow()
        self.isAuth = self.check_auth( response.body )
        if not self.isAuth:
            raise Exception("Could not login to %s", self.base_url)
        logging.info("Login to %s successfully, sid %s", self.base_url, self.sid)
        logging.debug("%s", str(response.headers))
        pass

    @gen.coroutine
    def download(self, url):
        if not self.isAuth or self.sid is None:
            self.login()

        m = re.search("viewtopic.php\\?(?:t|p)=(\\d+)", url)
        torrent = m.group(1)

        logging.info("Start download %s", url)
        request = HTTPRequest(
            url+'&sid=%s'%self.sid,
            headers = self.session.headers,
            method = 'GET',
            connect_timeout=5, request_timeout=20
        )
        response = yield self.client.fetch(request, raise_error = False)
        logging.info("Response code: %d %s", response.code, response.reason)
        response.rethrow()

        download_id = None
        match = re.search( "<a href=\"download.php\\?id=(\\d+)", response.body, re.I+re.M )
        if match:
            download_id = match.group(1)
        else:
            raise Exception("Could not find download id")

        # download
        url = "%sforum/download.php?id=%s&sid=%s" % (self.base_url, download_id, self.sid)
        logging.info("Start download %s", url)
        request = HTTPRequest(
            url,
            headers = self.session.headers,
            method = 'GET',
            connect_timeout=5, request_timeout=20
        )
        response = yield self.client.fetch(request, raise_error = False)
        logging.info("Response code: %d %s", response.code, response.reason)
        response.rethrow()
        raise gen.Return(response.body)
        pass

    @gen.coroutine
    def do_search(self, query):
        if query is None or query.strip()=='':
            raise gen.Return([])

        url = "%sforum/tracker.php" % self.base_url
        request = HTTPRequest(
                url,
                headers = self.session.headers,
                method = 'POST', 
                body = urllib.urlencode({
                  'f': u'-1', 'nm': query.encode('windows-1251'),'submit_search': (u'Поиск').encode('windows-1251'),
                }), connect_timeout=5, request_timeout=10
        )
        logging.info("Make request to %s", url)
        response = yield self.client.fetch( request, raise_error = False )
        logging.info("Response code: %d %s", response.code, response.reason)

        response.rethrow()

        tree = lxml.html.fromstring( response.body )
        sel = lxml.cssselect.CSSSelector( u"table.forumline.tablesorter tr.prow1,tr.prow2" )
        results = []
        for item in sel(tree):
            try:
               res = self.parse_result(item)
               results.append( res )
            except:
               logging.exception("Parsing error")

        raise gen.Return(results)
        pass


    def parse_result(self, element):
        cells = element.cssselect('td')

        href = cells[2].cssselect('a')[0].attrib['href']
        m = re.search('\?t=(.*)$', href)
        item_id = m.group(1)

        title    = cells[2].text_content().strip()
        category = cells[1].text_content().strip()

        size = 0
        added = 0
        try:
            size     = int(cells[5].cssselect('u')[0].text_content().strip())
            added    = int(cells[9].cssselect('u')[0].text_content().strip())
        except:
            pass
        return ResultItem(id="nnm_"+item_id, title=title, category=category, link=os.path.join(self.base_url,'forum/',href), added=added, size=size)


class Rutor(TrackerHelper):
    name = "new-rutor.org"

    def __init__(self, url, proxy ):
        TrackerHelper.__init__(self, url, proxy )
        self.client = AsyncHTTPClient()
        pass


    @gen.coroutine
    def do_search(self, query):
        if query.strip()=='':
            raise gen.Return([])

        url = u"%s/search/%s/" % (self.base_url, query )
        logging.info("Make request to %s", self.base_url)
        request = HTTPRequest(
                url,
                headers = self.session.headers,
                method = 'GET', 
                connect_timeout=5, request_timeout=10
        )
        response = yield self.client.fetch( request, raise_error = False )
        try:
            logging.info("Response code: %d %s", response.code, response.reason)
            response.rethrow()
        except:
            logging.exception("Error while connecting")
            raise gen.Return([])

        tree = lxml.html.fromstring( response.body )
        sel = lxml.cssselect.CSSSelector( u"tr.gai,tr.tum" )
        results = []
        for item in sel(tree):
           results.append( self.parse_result(item) )
        raise gen.Return(results)

    def parse_result(self, element):
        cells = element.cssselect('td')

        href     = cells[1].cssselect('a')[0].attrib['href']
        link     = self.base_url + href + '/'

        m = re.search('(\d+)$', href)
        item_id = m.group(1)

        title    = cells[1].cssselect('a')[1].text_content().strip()
        category = 'rutor'
        size     = cells[3].text_content().strip()

        date_str = cells[0].text_content().strip()
        added    = dateparser.parse( date_str, languages=['ru','en'] )# - datetime.datetime(1970, 1, 1) ).total_seconds() )
        if added != None:
            added = (added - datetime.datetime(1970, 1, 1) ).total_seconds()
        else:
            added = 0
        return ResultItem(id="_rutor_"+item_id, title=title, category=category, link=link, added=added, size=size)

    @gen.coroutine
    def download(self, url):
        m=re.search("rutor.org/torrent/(\\d+)", url)
        torrent = m.group(1)

        url = "http://new-rutor.org/parse/d.rutor.org/download/%s/" % torrent
        request = HTTPRequest(
            url,
            method='GET'
        )
        response = yield self.client.fetch( request, raise_on_error=False )
        response.rethrow()
        raise gen.Return(response.body)


class TorrentManager(object):
    @staticmethod
    def subclass_for(url):
        res = urlparse(url)
        for subclass in TorrentManager.__subclasses__():
            if subclass.name == res.scheme:
                return subclass
            pass
        return None

    def __init__(self, url):
        pass

    def get_torrents(self):
        return []

    def add_torrent(self, filename, torrent=None):
        pass


class TransmissionManager(TorrentManager):
    name = "transmission"

    def __init__(self, url):
        res = urlparse( url )
        self.client = AsyncHTTPClient()
        self.base_url = "http://%s:%d/transmission/rpc" % (res.hostname, res.port)
        self.headers = {'Content-Type': 'application/json'}
        pass

    @gen.coroutine
    def request(self, method, **kwargs):
        params = {'method': method, 'arguments': kwargs }
        logging.info("Make request method: %s", method)

        for i in range(2):
           request = HTTPRequest(
               self.base_url, method='POST',
               headers = self.headers,
               body = json.dumps(params),
               connect_timeout=5, request_timeout=10
           )
           response = yield self.client.fetch(request, raise_error=False)
           logging.info( response.body )
           if response.code == 409:
               self.headers['X-Transmission-Session-Id'] = response.headers['X-Transmission-Session-Id']
           else:
               raise gen.Return(json.loads(response.body))
        raise gen.Return(None)

    @gen.coroutine
    def get_torrents(self):
        logging.info("Get torrent list")
        result = []
        torrents = yield self.request('torrent-get', fields=['id', 'name', 'comment', 'hashString'])

        for t in torrents['arguments']['torrents']:
            info = {
               "id":  t['id'], 
               "name": t['name'],
               "url": t['comment'].strip(), 
               "info_hash": t['hashString'].upper()
            }
            result.append(info)
        raise gen.Return(result)

    @gen.coroutine
    def add_torrent(self, torrent_data, torrent=None):
        try:
            # Check downloaded torrent file for correctly and info_hash changed
            tr_info = bencode.bdecode( torrent_data )
            info_hash = self.info_hash( tr_info['info'] )

            if torrent is not None and torrent['info_hash']==info_hash:
                logging.info('No updates')
                return
            torrent_data = base64.b64encode(torrent_data)


            # Retrieve info about current torrent
            if torrent!=None:
                """
                torrent = self.client.get_torrent( torrent['id'] )
                download_dir = torrent.downloadDir
                unwanted_files = [k for k,v in torrent.files().iteritems() if not v['selected']  ]
                # add updated torrent
                self.client.add( torrent_data, download_dir=download_dir, files_unwanted=unwanted_files )
                # remove old torrent
                self.client.remove_torrent( torrent.id )"""
                pass
            else:
                response = yield self.request( method='torrent-add', metainfo=torrent_data )
            logging.info("Torrent data updated")
        except Exception, e:
            logging.exception("Bad torrent file")
        pass

    def info_hash(self, info):
        raw = bencode.bencode(info)
        m = hashlib.sha1()
        m.update( raw )
        return m.hexdigest().upper()


class UpdateChecker(BotRequestHandler):
    def __init__(self, manager, trackers, ioloop=None):
        self.ioloop   = ioloop or IOLoop.current()
        self.manager  = manager
        self.trackers = trackers
        self.renderer = ItemRenderer()
        self.cache = []
        pass

    def defaultCommand(self):
        return self.entry_point
    
    @authorized
    def entry_point(self, message=None):
        message_text = message['text']
        if message_text.startswith('/download'):
            self.do_download(message)
        else:
            self.do_search(message)
        pass

    @authorized
    def cmd_show(self, message=None):
        data = message['text'].split()

        search_id = int(data[1])
        start = int(data[2])
        if search_id>=0 and search_id<len(self.cache):
            chat_id = self.cache[search_id]['chat_id']
            message_id = self.cache[search_id]['message_id']
            results = self.cache[search_id]['results']

            self.show_results(search_id, chat_id, message_id, results, start)
        pass

    @authorized
    def cmd_update(self, message=None):
        pass

    def show_results(self, search_id, chat_id, message_id, results, start, page_size=3):
        message = 'Sorry, nothing is found'
        markup = None
        if len(results)>0:
            data = map( (lambda i: self.renderer.render(results[i]) ), range( start-1, min( start+page_size-1, len(results)) ) )
            message = u"\n".join(data)

            buttons=[]
            if start>page_size:
                buttons.append( {'text': "Prev %d/%d" % (page_size, start-1), 'callback_data': '/show %d %d'%(search_id, start-page_size)} )
            if (start+page_size) < len(results):
                buttons.append( {'text': "Next %d/%d" % (page_size, len(results)-start-page_size+1), 'callback_data': '/show %d %d'%(search_id, start+page_size)} )
    
            if len(buttons)>0:
                markup = {'inline_keyboard': [buttons]}

        self.bot.edit_message(
            to=chat_id, message_id=message_id, text=message, extra={'parse_mode': 'HTML'}, markup=markup
        )
        pass

    def do_search(self, message=None):
        query = message['text']

        def start_search(response):
            response.rethrow()
            result = json.loads(response.body)['result']

            chat_id = result['chat']['id']
            message_id = result['message_id']

            self.async_search(None, chat_id, message_id, query)
            pass

        # Send reply "search in progress" and start search
        self.bot.send_message(
            to=message['chat']['id'],
            reply_to_id=message['message_id'],
            text="Search in progress...",
            callback=start_search
        )
        pass

    @gen.coroutine
    def do_download(self, message=None):
        query = message['text']
        user_id = message['chat']['id']

        item_id = query.split('_',1)[1]
        logging.info("Search download url for id=%s", item_id)
        item = None
        for search in self.cache:
            for result in search['results']:
                if result.id == item_id:
                   item = result
                   break
            if item is not None:
                break

        if item is not None:
           url = item.link

           msg = yield self.bot.send_message(to=user_id, text='Downloading...')
           message_id = json.loads(msg.body)['result']['message_id']
           try:
               for tracker in self.trackers:
                   if tracker.check_url(url):
                      torrent_data = yield tracker.download(url)
                      tr_info = bencode.bdecode(torrent_data)
                      torrent_name = tr_info['info']['name']

                      result = yield self.manager.add_torrent(torrent_data)
                      self.bot.edit_message(to=user_id, message_id=message_id, text='Torrent "%s" downloaded' % torrent_name)
                      break
           except:
               logging.exception("Error while download torrent data")
               self.bot.edit_message(to=user_id, message_id=message_id, text="Sorry, error occured!\n%s" % traceback.format_exc())
        else:
           logging.warn("Couldn't find download url for id %s", item_id)

        raise gen.Return()

    @gen.coroutine
    def async_search(self, search_id, chat_id, message_id, query):
        if search_id is None:
            search_id = len(self.cache)
            self.cache.append({
                'chat_id': chat_id, 'message_id': message_id, 'query': query, 'results': []
            })
        logging.info("Start search_id %d for query \"%s\"", search_id, query)
        
        responses = yield [tracker.do_search(query) for tracker in self.trackers]
        results = []
        for response in responses:
            results = results + response
        logging.info("Found %d torrents", len(results))
        self.cache[search_id]['results'] = results
        self.show_results(search_id, chat_id, message_id, results, 1)
        pass

    def do_update(self):
        """
        torrents = self.manager.get_torrents()
        for torrent in torrents:
            logging.info( "Checking updates of \"%s\"", torrent['name'] )
            torrent_data = self._download_torrent(torrent['url'], torrent['info_hash'])
            if torrent_data!=None:
                self.manager.add_torrent(torrent_data, torrent)
            pass"""
        pass
        

def main():
    class LoadFromFile( argparse.Action ):
        def __call__(self, parser, namespace, values, option_string = None):
           with values as f:
               parser.parse_args(f.read().split(), namespace)

    parser = argparse.ArgumentParser(fromfile_prefix_chars='@')

    basic = parser.add_argument_group('basic','Basic parameters')
    basic.add_argument("-c", "--config", type=open, action=LoadFromFile, help="Load config from file")
    basic.add_argument("--cookies",  default="cookies.dat")
    basic.add_argument("--timeout", default=10, type=int)
    basic.add_argument("--token",   help="Telegram API bot token")
    basic.add_argument("--admin",   nargs="+", help="Bot admin", type=int, dest="admins")
    basic.add_argument("--logfile", help="Logging into file")
    basic.add_argument("--tmp",    default=".", dest="path")
    basic.add_argument("-v", action="store_true", default=False, help="Verbose logging", dest="verbose")
    basic.add_argument("-m","--manager", dest="manager", default="transmission://127.0.0.1:9091")

    download = parser.add_argument_group('download', 'Download helper parameters')
    download.add_argument("--helper",  action="append", default=[] )
    download.add_argument("--download-dir", dest="download_dir", default=".")
    download.add_argument("--proxy")

    params = parser.parse_args()

    logging.basicConfig(
        format = u'%(asctime)s\t%(process)d\t%(levelname)s\t%(message)s',
        level = logging.DEBUG if params.verbose else logging.INFO,
        filename=params.logfile
    )
    # Configure tracker global params
    TrackerHelper.init( params.cookies, params.timeout, params.path )

    trackers = [ TrackerHelper.subclass_for(url)(url, params.proxy)  for url in params.helper if TrackerHelper.subclass_for(url) is not None ]
    logging.info( "tracker support loaded: %s", ",".join([str(tr.name) for tr in trackers]) )
    for tracker in trackers:
        tracker.login()

    manager_class = TorrentManager.subclass_for( params.manager )
    if manager_class is None:
        logging.error("Unknown torrent manager scheme")
        exit()
    manager = manager_class( params.manager )

    updater = UpdateChecker( manager, trackers )
    ioloop = IOLoop.instance()

    bot = Bot(params.token, params.admins, ioloop=ioloop)
    bot.addHandler(updater)

    bot.loop_start()
    try:
       ioloop.start()
    except KeyboardInterrupt, e:
       ioloop.stop()
    finally:
       pass
    pass

    TrackerHelper.finish()
    return

if __name__=="__main__":
    main()
