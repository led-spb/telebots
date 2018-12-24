import json
import logging
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado import gen
from uuid import uuid4
from functools import partial
from datetime import timedelta

def authorized(func):
    def wrapped(self, message):
        admins = self.bot.admins
        if message is None or message['from']['id'] in admins:
            return func(self, message)
        else:
            self.bot.logger.warn(
                "User %d/%s %s is unauthorized",
                message['from']['id'], 
                message['from']['first_name'],
                message['from']['last_name']
            )
    return wrapped


class BotRequestHandler:
    def commands(self):
        return ['/'+x[4:] for x in dir(self) if x.find('cmd_') == 0]

    def getCommand(self, name):
        if name.find('/') == 0 and hasattr(self, "cmd_"+name[1:]):
            return getattr(self, "cmd_"+name[1:])
        else:
            return self.defaultCommand()

    def defaultCommand(self):
        return None

    def assignTo(self, bot):
        self.bot = bot


class Bot():

    def __init__(self, token, admins=None, handler=None, logger=None, proxy=None, ioloop=None):
        self.logger = logger or logging.getLogger(self.__class__.__name__)

        self.token = token
        self.admins = admins or []
        self.proxy = proxy

        self.baseUrl = 'https://api.telegram.org/bot%s' % self.token
        self.handlers = []
        if handler is not None:
            self.addHandler(handler)

        self.ioloop = ioloop or IOLoop.current()
        self._client = AsyncHTTPClient()
        self.params = {'timeout': 60, 'offset': 0, 'limit': 5}


    def addHandler(self, handler):
        if handler is not None:
            handler.assignTo(self)
            self.handlers.append(handler)
        pass

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

    def exec_command(self, message):
        self.logger.debug( json.dumps(message, indent=2) )
        if 'text' in message:
             params = message['text'].lower().split()
             command = params[0]
             self.logger.info('Processing command %s (%s)', command, ", ".join(params[1:]) )

             for handler in self.handlers:
                 functor = handler.getCommand(command)
                 if functor is not None:
                     functor.__call__( message )
        else:
             raise Exception('Only text messages supported')
        pass

    def process_updates(self, updates):
        for update in updates:
            if 'callback_query' in update:
                callback = update['callback_query']
                self.process_callback( callback )

                message = callback['message']
                message['from'] = callback['from']
                message['text'] = callback['data']
                update.update({'message': message})

            if 'message' in update:
                message = update['message']
                if 'from' in message:
                    user = message['from']
                    message_type = "unknown"
                    if "text" in message:
                       message_type = message["text"]
                    if "contact" in message:
                       message_type = "contact"
                    if "location" in message:
                       message_type = "location"
                    if "document" in message:
                       message_type = "document"

                    self.logger.info(
                         "request \"%s\" from %d/%s",
                         message_type,
                         message['from']['id'],
                         message['from']['first_name']
                    )
                    try:
                        self.exec_command( message )
                    except:
                        logging.exception('Error while processing request')
            self.params['offset'] = update['update_id']+1
        return

    def process_callback(self, callback):
        client = AsyncHTTPClient()
        request = HTTPRequest(
            self.baseUrl + '/answerCallbackQuery?callback_query_id=%s' % callback['id']
        )
        return client.fetch(request, raise_error=False)
        pass

    def _on_updates_ready(self, response):
        try:
            response.rethrow()
            result = json.loads(response.body)

            self.logger.debug('updates:')
            self.logger.debug(json.dumps(result, indent=2))
            if result['ok']:
               updates = result['result']
               try:
                  self.process_updates(updates)
               except:
                  self.logger.exception(
                      'Error while processing updates'
                  )
            else:
               self.logger.error(
                    'Error while recieve updates from server'
               )
               self.logger.error(result)

            self.loop_start()
        except:
            self.logger.exception(
                    'Error while recieve updates from server'
            )
            self.loop_start(10)
            pass

    def _on_message_cb( self, response ):
        try:
            response.rethrow()
        except:
            self.logger.exception("Error while sending message")
        pass

    def loop_start(self, delay=0):
        if delay>0:
            self.ioloop.add_timeout(timedelta(seconds=15), self.request_loop)
        else:
            self.ioloop.add_callback(self.request_loop)

    @gen.coroutine
    def multipart_producer( self, boundary, body, files, write ):
        boundary_bytes = boundary.encode()

        for key, value in body.iteritems():
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

    def send_request( self, url, method='GET', body=None, files={}, timeout=15, callback=None ):
        client = AsyncHTTPClient()
        if len(files)==0:
            request = HTTPRequest( url, 
                headers = { "Content-Type": "application/json" },
                method = 'POST', body = json.dumps(body)
            )
        else:
            boundary = uuid4().hex
            request = HTTPRequest( url, 
                headers = {"Content-Type": "multipart/form-data; boundary=%s" % boundary},
                method = 'POST', 
                body_producer = partial( 
                    self.multipart_producer,
                    boundary, body, files
                )
            )
        return client.fetch( request, callback=callback or self._on_message_cb, raise_error = False )

    def edit_message( self, to, message_id, text, markup=None, extra=None, callback=None ):
        params = {'chat_id': to, 'message_id': message_id, 'text': text}
        if markup is not None:
            params['reply_markup'] = json.dumps(markup)
        if extra is not None:
            for key, val in extra.iteritems():
                params[key] = val

        return self.send_request( 
                   self.baseUrl + '/editMessageText',
                   method = 'POST', body=params, 
                   timeout=10, 
                   callback=callback
        )

    def send_message(
            self, to, text=None, photo=None, video=None,
            audio=None, voice=None, document=None, markup=None, 
	    latitude=None, longitude=None, reply_to_id=None, extra=None, callback=None):
        params = {'chat_id': to}
        files = {}

        if photo is not None:
            method = 'Photo'
            files['photo'] = photo
        elif voice is not None:
            method = 'Voice'
            files['voice'] = voice
        elif audio is not None:
            method = 'Audio'
            files['audio'] = audio
        elif video is not None:
            method = 'Video'
            files['video'] = video
        elif document is not None:
            method = 'Document'
            files['document'] = document
        elif latitude is not None:
            method = 'Location'
            params['latitude']  = latitude
            params['longitude'] = longitude
        else:
            method = 'Message'
            params['text'] = text

        if markup is not None:
            params['reply_markup'] = json.dumps(markup)
        if reply_to_id is not None:
            params['reply_to_message_id'] = reply_to_id

        if extra is not None:
            for key, val in extra.iteritems():
                params[key] = val

        return self.send_request( self.baseUrl + '/send%s' % (method),
               method = 'POST', body=params, files=files, timeout=10, callback=callback
        )
        pass
