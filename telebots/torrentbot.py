#!/usr/bin/python
# -*- coding: utf-8 -*-
import re
import os
import cookielib
import argparse
import hashlib
import json
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
import tornado.web
from tornado import gen
from pytelegram_async.bot import Bot, BotRequestHandler, PatternMessageHandler
from jinja2 import Environment
import telebots


class Renderer(object):

    def __init__(self, template=None):
        self.jinja2 = Environment()
        self.jinja2.filters['datetimeformat'] = self._datetimeformat
        self.jinja2.filters['todatetime'] = self._todatetime
        if template is not None:
            self.template = template

    @property
    def template(self):
        return self._template

    @template.setter
    def template(self, value):
        self._template = self.jinja2.from_string(value)

    @staticmethod
    def _datetimeformat(value, format='%d-%m-%Y %H:%M:%s'):
        return value.strftime(format)

    @staticmethod
    def _todatetime(value):
        return datetime.fromtimestamp(int(value))

    def render(self, item):
        return self.template.render(item=item)


class ResultItem:
    __attributes__ = ['id', 'title', 'category', 'link', 'added', 'size']

    def __init__(self, **kwargs):
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
        TrackerHelper.cookies = cookielib.MozillaCookieJar(cookie)
        try:
            TrackerHelper.cookies.load(ignore_discard=True, ignore_expires=True)
        except Exception:
            pass
        TrackerHelper.timeout = timeout
        TrackerHelper.torrent_path = path
        return

    @staticmethod
    def finish():
        try:
            TrackerHelper.cookies.save(ignore_discard=True, ignore_expires=True)
        except Exception:
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
        self.user = res.username
        self.passwd = res.password
        self.base_url = "%s://%s/" % (res.scheme, res.hostname)

        self.cookies = TrackerHelper.cookies
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/29.0.1547.66 Safari/537.36',
            'Accept-Charset': 'utf-8'
        }
        self.proxies = {}
        if proxy is not None:
            self.proxies = {'http': proxy}
        pass

    def login(self):
        pass

    def check_url(self, url):
        names = [self.name] if not isinstance(self.name, list) else self.name
        for name in names:
            if re.search('^http://%s' % name, url) is not None:
                return True
        return False

    def download(self, url):
        pass

    def do_search(self, query):
        pass


class NonameClub(TrackerHelper):
    name = ["nnm-club.me", "nnmclub.to"]

    def __init__(self, url, proxy):
        TrackerHelper.__init__(self, url, proxy)
        self.isAuth = False
        self.sid = None
        self.client = AsyncHTTPClient()
        self.timeout = 40
        pass

    def check_auth(self, body):
        if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
            with open("login.dat","w") as f:
                f.write(body)
                f.close()

        m = re.search(r'<a\s+href="login\.php\?logout=true&amp;sid=(.*?)"', body, re.I + re.M)
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
        logging.info("Unauthorized, start connection to %s", url)
        request = HTTPRequest(
            url,
            headers=self.headers,
            method='GET',
            connect_timeout=5, request_timeout=self.timeout
        )
        response = yield self.client.fetch(request, raise_error=False)
        logging.debug("Response code: %d %s", response.code, response.reason)
        logging.debug("%s", str(response.headers))
        response.rethrow()

        m = re.search(r'<form.*?action="login.php".*?>(.*?)</form>', response.body, re.I + re.M + re.U + re.S)
        form = m.group(1)
        login_data = {
            'login': u'Вход'.encode('windows-1251'),
            'username': self.user, 'password': self.passwd,
            'autologin': 'on'
        }
        for m in re.finditer(r'<input\s+type="hidden"\s+name="(.*?)"\s+value="(.*?)"', form, re.I + re.M + re.S):
            login_data[m.group(1)] = m.group(2)

        request = HTTPRequest(
            url, headers=self.headers, method='POST', body=urllib.urlencode(login_data),
            connect_timeout=5, request_timeout=self.timeout
        )
        logging.info("Passing credentials to %s", self.base_url)
        response = yield self.client.fetch(request, raise_error=False)
        logging.debug("Response code: %d %s", response.code, response.reason)

        response.rethrow()
        self.isAuth = self.check_auth(response.body)
        if not self.isAuth:
            raise Exception("Could not login to %s", self.base_url)
        logging.info("Login to %s successfully, sid %s", self.base_url, self.sid)
        logging.debug("%s", str(response.headers))
        pass

    @gen.coroutine
    def download(self, url):
        if not self.isAuth or self.sid is None:
            yield self.login()
        logging.info("Find download url for %s", url)

        match = re.search(r'viewtopic\.php\?p=(\d+)$', url)
        if match:
            topic_id = match.group(1)
            url = "%sforum/viewtopic.php?p=%s" % (self.base_url, topic_id)
            logging.info('URL rewrited to %s', url)

        request = HTTPRequest(
            url + '&sid=%s' % self.sid,
            headers=self.headers,
            method='GET',
            connect_timeout=5, request_timeout=self.timeout
        )
        response = yield self.client.fetch(request, raise_error=False)
        logging.debug("Response code: %d %s", response.code, response.reason)
        response.rethrow()

        match = re.search("<a href=\"download.php\\?id=(\\d+)", response.body, re.I + re.M)
        if match:
            download_id = match.group(1)
        else:
            self.isAuth = False
            raise Exception("Could not find download url")

        # download
        url = "%sforum/download.php?id=%s&sid=%s" % (self.base_url, download_id, self.sid)
        logging.info("Found download url %s", url)
        request = HTTPRequest(
            url,
            headers=self.headers,
            method='GET',
            connect_timeout=5, request_timeout=self.timeout
        )
        response = yield self.client.fetch(request, raise_error=False)
        logging.debug("Response code: %d %s", response.code, response.reason)
        response.rethrow()
        raise gen.Return(response.body)
        pass

    @gen.coroutine
    def do_search(self, query):
        if query is None or query.strip() == '':
            raise gen.Return([])

        url = "%sforum/tracker.php" % self.base_url
        request = HTTPRequest(
            url,
            headers=self.headers,
            method='POST',
            body=urllib.urlencode({
                'f': u'-1', 'nm': query.encode('windows-1251'), 'submit_search': u'Поиск'.encode('windows-1251'),
            }), connect_timeout=5, request_timeout=self.timeout
        )
        logging.info("Make search request to %s", url)
        response = yield self.client.fetch(request, raise_error=False)
        logging.debug("Response code: %d %s", response.code, response.reason)

        response.rethrow()

        tree = lxml.html.fromstring(response.body)
        sel = lxml.cssselect.CSSSelector(u"table.forumline.tablesorter tr.prow1,tr.prow2")
        results = []
        for item in sel(tree):
            try:
                res = self.parse_result(item)
                results.append(res)
            except Exception:
                logging.exception("Parsing error")

        raise gen.Return(results)
        pass

    def parse_result(self, element):
        cells = element.cssselect('td')

        href = cells[2].cssselect('a')[0].attrib['href']
        m = re.search(r'\?t=(.*)$', href)
        item_id = m.group(1)

        title = cells[2].text_content().strip()
        category = cells[1].text_content().strip()

        size = 0
        added = 0
        try:
            size = int(cells[5].cssselect('u')[0].text_content().strip())
            added = int(cells[9].cssselect('u')[0].text_content().strip())
        except Exception:
            pass

        item = ResultItem(id="nnm_" + item_id,
                          title=title,
                          category=category,
                          link=os.path.join(self.base_url, 'forum/', href),
                          added=added,
                          size=size
                          )
        return item


class Rutor(TrackerHelper):
    name = "new-rutor.org"

    def __init__(self, url, proxy):
        TrackerHelper.__init__(self, url, proxy)
        self.client = AsyncHTTPClient()
        pass

    @gen.coroutine
    def do_search(self, query):
        if query.strip() == '':
            raise gen.Return([])

        url = u"%s/search/%s/" % (self.base_url, query)
        logging.info("Make request to %s", self.base_url)
        request = HTTPRequest(
            url,
            headers=self.headers,
            method='GET',
            connect_timeout=5, request_timeout=10
        )
        response = yield self.client.fetch(request, raise_error=False)
        try:
            logging.debug("Response code: %d %s", response.code, response.reason)
            response.rethrow()
        except Exception:
            logging.exception("Error making request")
            raise gen.Return([])

        tree = lxml.html.fromstring(response.body)
        sel = lxml.cssselect.CSSSelector(u"tr.gai,tr.tum")
        results = []
        for item in sel(tree):
            results.append(self.parse_result(item))
        raise gen.Return(results)

    def parse_result(self, element):
        cells = element.cssselect('td')

        href = cells[1].cssselect('a')[0].attrib['href']
        link = self.base_url + href + '/'

        m = re.search(r'(\d+)$', href)
        item_id = m.group(1)

        title = cells[1].cssselect('a')[1].text_content().strip()
        category = 'rutor'
        size = cells[3].text_content().strip()

        # date_str = cells[0].text_content().strip()
        added = None
        # added = dateparser.parse(date_str, languages=['ru','en'] )# - datetime.datetime(1970, 1, 1) ).total_seconds())
        if added is not None:
            added = (added - datetime.datetime(1970, 1, 1)).total_seconds()
        else:
            added = 0
        return ResultItem(id="_rutor_" + item_id, title=title, category=category, link=link, added=added, size=size)

    @gen.coroutine
    def download(self, url):
        m = re.search(r'rutor.org/torrent/(\d+)', url)
        torrent = m.group(1)

        url = "http://new-rutor.org/parse/d.rutor.org/download/%s/" % torrent
        request = HTTPRequest(
            url,
            method='GET'
        )
        response = yield self.client.fetch(request, raise_on_error=False)
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

    def add_torrent(self, filename, old_torrent_info=None):
        pass


class TransmissionManager(TorrentManager):
    name = "transmission"

    def __init__(self, url):
        TorrentManager.__init__(self, url)
        res = urlparse(url)

        self.client = AsyncHTTPClient()
        self.base_url = "http://%s:%d/transmission/rpc" % (res.hostname, res.port)
        self.headers = {'Content-Type': 'application/json'}
        pass

    @gen.coroutine
    def request(self, method, **kwargs):
        params = {'method': method, 'arguments': kwargs}
        logging.debug("Make request method: %s", method)

        for i in range(2):
            request = HTTPRequest(
                self.base_url, method='POST',
                headers=self.headers,
                body=json.dumps(params),
                connect_timeout=5, request_timeout=10
            )
            response = yield self.client.fetch(request, raise_error=False)
            logging.debug(response.body)
            if response.code == 409:
                self.headers['X-Transmission-Session-Id'] = response.headers['X-Transmission-Session-Id']
            else:
                result = json.loads(response.body)
                if result['result'] != 'success':
                    raise RuntimeError(result['result'])
                raise gen.Return(result.get('arguments'))
        raise gen.Return(None)

    @gen.coroutine
    def get_torrents(self):
        logging.debug("Get torrent list")
        result = []
        response = yield self.request(
            'torrent-get',
            fields=[
                'id', 'name', 'comment', 'hashString', 'status', 'errorString', 'metadataPercentComplete',
                'files', 'fileStats', 'downloadDir'
            ]
        )

        for t in response['torrents']:
            files = [dict(f[0], **f[1]) for f in zip(t['files'], t['fileStats'])]

            info = {
                'id': t['id'],
                'name': t['name'],
                'url': t['comment'].strip(),
                'error': t['errorString'].strip(),
                'status': t['status'],
                'done': t['metadataPercentComplete'],
                'info_hash': t['hashString'].upper(),
                'downloadDir': t['downloadDir'],
                'files': files
            }
            result.append(info)
        raise gen.Return(result)

    @gen.coroutine
    def add_torrent(self, torrent_data, old_torrent_info=None):
        try:
            # Check downloaded torrent file for correctly and info_hash changed
            tr_info = bencode.bdecode(torrent_data)
            info_hash = self.info_hash(tr_info['info'])
        except Exception:
            logging.exception("Bad torrent file")
            raise ValueError("Bad torrent file")

        if old_torrent_info is not None and old_torrent_info['info_hash'] == info_hash:
            logging.info('No updates')
            raise gen.Return(False)

        torrent_data = base64.b64encode(torrent_data)

        if old_torrent_info is not None:
            unwanted = [k for k, v in enumerate(old_torrent_info['files']) if not v['wanted']]

            yield self.request(**{
                'method': 'torrent-add',
                'metainfo': torrent_data,
                'download-dir': old_torrent_info['downloadDir'],
                'files-unwanted': unwanted
            })

            yield self.request(
                method='torrent-remove',
                ids=[old_torrent_info['id']]
            )
            pass
        else:
            yield self.request(method='torrent-add', metainfo=torrent_data)
        logging.info("Torrent data updated")
        raise gen.Return(True)
        pass

    @staticmethod
    def info_hash(info):
        raw = bencode.bencode(info)
        m = hashlib.sha1()
        m.update(raw)
        return m.hexdigest().upper()


class UpdateChecker(BotRequestHandler):
    def __init__(self, manager, trackers, ioloop=None):
        BotRequestHandler.__init__(self)
        self.ioloop = ioloop or IOLoop.current()
        self.manager = manager
        self.trackers = trackers

        self.search_renderer = Renderer(
            u"<b>{{item.title|e}}</b>\n"
            u"Раздел: {{item.category|e}}\n"
            u"Размер: {% if item.size | int(-1) == -1 %}{{item.size | e}}{% else %}"
            u"{{ item.size | default(0) | int | filesizeformat }}{% endif %}\n"
            u"Добавлено: {{ item.added | default(0) | int | todatetime | datetimeformat('%d-%m-%Y') }}\n"
            u"Скачать: /download_{{item.id}}\n"
            u"\n"
        )
        self.torrent_renderer = Renderer(
            u"<b>{{ item.name | e }}</b> - {{ \"%0.2f\" | format(item.done*100) }}% done\n\n"
        )
        self.cache = []
        self.update_task = PeriodicCallback(self.do_update, 15 * 60 * 1000)
        self.version = telebots.version
        pass

    @PatternMessageHandler('/show( .*)?', authorized=True)
    def cmd_show(self, chat, text):
        data = text.split()

        search_id = int(data[1])
        start = int(data[2])
        if 0 <= search_id < len(self.cache):
            chat_id = self.cache[search_id]['chat_id']
            message_id = self.cache[search_id]['message_id']
            results = self.cache[search_id]['results']

            self.show_results(search_id, chat_id, message_id, results, start)
        return True

    @PatternMessageHandler('/status', authorized=True)
    def cmd_status(self, message_id, chat):
        @gen.coroutine
        def execute():
            torrents = yield self.manager.get_torrents()
            text = [self.torrent_renderer.render(x) for x in torrents]
            self.bot.send_message(
                to=chat['id'], message="".join(text), reply_to_message_id=message_id, parse_mode='HTML'
            )
        execute()
        return True

    @PatternMessageHandler('/update( .*)?', authorized=True)
    def cmd_update(self, chat, text):
        cmd = text.split()
        chat_id = chat['id']
        if len(cmd) == 1:
            buttons = [
                {'text': 'Now', 'callback_data': '/update now'},
                {'text': '15m', 'callback_data': '/update 15'},
                {'text': '30m', 'callback_data': '/update 30'},
                {'text': '60m', 'callback_data': '/update 60'},
                {'text': 'Off', 'callback_data': '/update 0'},
            ]
            markup = {'inline_keyboard': [buttons]}
            self.bot.send_message(to=chat_id, message='Schedule update', reply_markup=markup)
        else:
            when = cmd[1]
            if when == 'now':
                self.do_update(chat_id)
            else:
                minutes = int(when)
                if self.update_task.is_running():
                    self.update_task.stop()

                if minutes > 0:
                    self.update_task = PeriodicCallback(self.do_update, minutes * 60 * 1000)
                    self.update_task.start()
                    text = 'Schedule updated: Each %d minutes' % minutes
                else:
                    text = 'Schedule updated: off'

                self.bot.send_message(to=chat_id, message=text)
            pass
        return True

    def show_results(self, search_id, chat_id, message_id, results, start, page_size=3):
        message = 'Sorry, nothing is found'
        markup = None
        if len(results) > 0:
            data = map(
                (lambda i: self.search_renderer.render(results[i])),
                range(start - 1, min(start + page_size - 1, len(results)))
            )
            message = u"\n".join(data)

            buttons = []
            if start > page_size:
                buttons.append({
                    'text': "Prev %d/%d" % (page_size, start - 1),
                    'callback_data': '/show %d %d' % (search_id, start - page_size)
                })
            if (start + page_size) < len(results):
                buttons.append({
                    'text': "Next %d/%d" % (page_size, len(results) - start - page_size + 1),
                    'callback_data': '/show %d %d' % (search_id, start + page_size)
                })

            if len(buttons) > 0:
                markup = {'inline_keyboard': [buttons]}

        self.bot.edit_message_text(
            to=chat_id, message_id=message_id, text=message, parse_mode='HTML', reply_markup=markup
        )
        pass

    @PatternMessageHandler('[^/].*', authorized=True)
    def do_search(self, text, chat, message_id):
        query = text
        chat_id = chat['id']

        @gen.coroutine
        def execute():
            # Send reply "search in progress"
            msg = yield self.bot.send_message(
                to=chat_id,
                message="Search in progress...",
                reply_to_message_id=message_id
            )
            placeholder_message_id = json.loads(msg.body)['result']['message_id']
            self.async_search(None, chat_id, placeholder_message_id, query)
        execute()
        return True

    @PatternMessageHandler('/download_.*', authorized=True)
    def do_download(self, chat, text):
        query = text
        user_id = chat['id']

        @gen.coroutine
        def execute():
            item_id = query.split('_', 1)[1]
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

                msg = yield self.bot.send_message(to=user_id, message='Downloading...')
                message_id = json.loads(msg.body)['result']['message_id']
                try:
                    for tracker in self.trackers:
                        if tracker.check_url(url):
                            torrent_data = yield tracker.download(url)
                            tr_info = bencode.bdecode(torrent_data)
                            torrent_name = tr_info['info']['name']

                            yield self.manager.add_torrent(torrent_data)
                            self.bot.edit_message_text(
                                to=user_id, message_id=message_id, text='Torrent "%s" downloaded' % torrent_name
                            )
                            break
                except Exception:
                    logging.exception("Error while download torrent data")
                    self.bot.edit_message_text(
                        to=user_id, message_id=message_id, text="Sorry, error occurred!\n%s" % traceback.format_exc()
                    )
            else:
                logging.warn("Couldn't find download url for id %s", item_id)
        execute()
        return True

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

    @gen.coroutine
    def do_update(self, reply_chat_id=None):
        chat_id = reply_chat_id or self.bot.admins[0]
        updated = False
        torrents = yield self.manager.get_torrents()
        error = False

        for torrent in torrents:
            url = torrent['url']
            logging.info('Checking updates for %s', url)
            for tracker in self.trackers:
                if tracker.check_url(url):
                    logging.debug('Download using %s', tracker.__class__)
                    try:
                        torrent_data = yield tracker.download(url)
                        added = yield self.manager.add_torrent(torrent_data, torrent)
                        if added:
                            updated = True
                            self.bot.send_message(
                                to=chat_id,
                                message='Torrent "%s" updated' % torrent['name']
                            )
                    except Exception as e:
                        logging.exception('Error while check updates')
                        if reply_chat_id is not None:
                            self.bot.send_message(
                                to=chat_id, message=traceback.format_exc()
                            )
                        error = True
                    continue
            pass

        if not error and not updated and reply_chat_id is not None:
            self.bot.send_message(
                to=chat_id,
                message='No updates'
            )
        pass

    def do_notify(self, message):
        logging.info("Notify message: \"%s\"", message)
        chat_id = self.bot.admins[0]
        self.bot.send_message(
            to=chat_id,
            message=message
        )
        pass


class HTTPRequestHandler(tornado.web.RequestHandler):

    def initialize(self, **kwargs):
        for attr, value in kwargs.iteritems():
            setattr(self, attr, value)

    @tornado.web.asynchronous
    def post(self, *args, **kwargs):
        self.updater.do_notify(self.request.body)

        self.set_status(200)
        self.write('')
        self.finish()
        pass


def main():
    import shlex

    class LoadFromFile(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            with values as f:
                parser.parse_args(shlex.split(f.read()), namespace)

    parser = argparse.ArgumentParser(fromfile_prefix_chars='@')

    basic = parser.add_argument_group('basic', 'Basic parameters')
    basic.add_argument("-c", "--config", type=open, action=LoadFromFile, help="Load config from file")
    basic.add_argument("--cookies", default="cookies.dat")
    basic.add_argument("--timeout", default=10, type=int)
    basic.add_argument("--token", help="Telegram API bot token")
    basic.add_argument("--admin", nargs="+", help="Bot admin", type=int, dest="admins")
    basic.add_argument("--logfile", help="Logging into file")
    basic.add_argument("--tmp", default=".", dest="path")
    basic.add_argument("-v", action="store_true", default=False, help="Verbose logging", dest="verbose")
    basic.add_argument("-m", "--manager", dest="manager", default="transmission://127.0.0.1:9091")
    basic.add_argument("--http-port", dest="http_port", type=int, default=None)

    download = parser.add_argument_group('download', 'Download helper parameters')
    download.add_argument("--helper", action="append", default=[])
    download.add_argument("--download-dir", dest="download_dir", default=".")
    download.add_argument("--proxy")

    params = parser.parse_args()

    logging.basicConfig(
        format=u'%(asctime)s\t%(process)d\t%(levelname)s\t%(message)s',
        level=logging.DEBUG if params.verbose else logging.INFO,
        filename=params.logfile
    )
    # Configure tracker global params
    TrackerHelper.init(params.cookies, params.timeout, params.path)

    trackers = [TrackerHelper.subclass_for(url)(url, params.proxy) for url in params.helper if
                TrackerHelper.subclass_for(url) is not None]
    logging.info("tracker support loaded: %s", ",".join([str(tr.name) for tr in trackers]))
    #for tracker in trackers:
    #    tracker.login()

    manager_class = TorrentManager.subclass_for(params.manager)
    if manager_class is None:
        logging.error("Unknown torrent manager scheme")
        exit()
    manager = manager_class(params.manager)

    updater = UpdateChecker(manager, trackers)
    if params.http_port is not None:
        webapp = tornado.web.Application(
            [(r'/download/done', HTTPRequestHandler, {'updater': updater})]
        )
        webapp.listen(port=params.http_port)

    ioloop = IOLoop.instance()

    bot = Bot(params.token, params.admins, ioloop=ioloop)
    bot.add_handler(updater)

    bot.loop_start()
    try:
        ioloop.start()
    except KeyboardInterrupt:
        ioloop.stop()
    finally:
        pass
    pass

    TrackerHelper.finish()
    return


if __name__ == "__main__":
    main()
