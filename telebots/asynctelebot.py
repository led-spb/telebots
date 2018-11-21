from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado import gen
from telebot import Bot
import json
from uuid import uuid4
from functools import partial


class AsyncBot(Bot):

    def __init__(self, token, admins, handler=None, logger=None, proxy=None, ioloop=None):
        self.ioloop = ioloop or IOLoop.current()
        self._client = AsyncHTTPClient()
        self.params = {'timeout': 60, 'offset': 0, 'limit': 5}
        Bot.__init__(self, token, admins, handler, logger, proxy)
     
    def request_loop(self):
        request = HTTPRequest(
            url = self.baseUrl+'/getUpdates',
            method = 'POST',
            headers = { "Content-Type": "application/json" },
            body = json.dumps( self.params ),
            request_timeout = self.params['timeout']+5
        )
        self._client.fetch( request, callback = self._on_updates_ready, raise_error = False )
        return

    def _on_updates_ready(self, response):
        try:
            response.rethrow()
            result = json.loads(response.body)

            self.logger.debug('updates:')
            self.logger.debug(json.dumps(result, indent=2))
            if result['ok']:
               updates = result['result']
               self.process_updates(updates)
            else:
               self.logger.error(
                    'Error while recieve updates from server'
               )
               self.logger.error(result)
        except:
            self.logger.exception(
                    'Error while recieve updates from server'
            )
            pass
        self.loop_start()

    def _on_message_cb( self, response ):
        try:
            response.rethrow()
        except:
            self.logger.exception("Error while sending message")
        pass

    def loop_start(self):
        self.ioloop.add_callback( self.request_loop )

    def loop_stop(self):
        pass

    def loop_forever(self):
        pass

    def process_callback(self, callback):
        client = AsyncHTTPClient()
        request = HTTPRequest(
            self.baseUrl + '/answerCallbackQuery?callback_query_id=%s' % callback['id']
        )
        client.fetch(request, callback = self._on_message_cb, raise_error=False)
        pass

    @gen.coroutine
    def multipart_producer( self, boundary, body, files, write ):
        boundary_bytes = boundary.encode()

        for key, value in body.iteritems():
            self.logger.debug("BODY: %s: %s", key, value)
            buf = ( 
                   ( b'--%s\r\n' % (boundary_bytes,)) 
                   + ( b'Content-Disposition: form-data; name="%s"\r\n' % key.encode() )
                   + ( b'\r\n%s\r\n' % str(value).encode() )
              )
            yield write(buf)

        for key, value in files.iteritems():
            filename = value[0]
            f = value[1]
            mtype = value[2]
            self.logger.debug("FILE: %s: %s %s", key, filename, mtype)

            buf = (
                  (b"--%s\r\n" % boundary_bytes)
                  + (
                      b'Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
                       % (key.encode(), filename.encode())
                    )
                  + (b"Content-Type: %s\r\n" % mtype.encode())
                  + b"\r\n"
            )
            yield write(buf)

            while True:
                chunk = f.read(16 * 1024)
                if not chunk:
                    break
                yield write(chunk)
            yield write(b"\r\n")

        yield write(b"--%s--\r\n" % (boundary_bytes,))
        pass

    def send_request( self, url, method='GET', body=None, files={}, timeout=15 ):
        client = AsyncHTTPClient()
        if len(files)==0:
            request = HTTPRequest( url, 
                headers = { "Content-Type": "application/json" },
                method = 'POST', body = json.dumps(body), request_timeout=timeout
            )
        else:
            boundary = uuid4().hex
            #producer = self.multipart_producer( boundary, body, files )
            request = HTTPRequest( url, 
                headers = {"Content-Type": "multipart/form-data; boundary=%s" % boundary},
                method = 'POST', 
                body_producer = partial( 
                    self.multipart_producer,
                    boundary, body, files
                ),
                request_timeout=timeout
            )
        client.fetch( request, callback=self._on_message_cb, raise_error = False )
        return
   