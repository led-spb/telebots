import requests
import logging
import json
import time
import threading
import traceback


class BotRequestHandler:
    def commands(self):
        return ['/'+x[4:] for x in dir(self) if x.find('cmd_') == 0]

    def getEvent(self, name):
        if hasattr(self, "event_"+name):
            return getattr(self, "event_"+name)
        else:
            return None

    def getCommand(self, name):
        if name.find('/') == 0 and hasattr(self, "cmd_"+name[1:]):
            return getattr(self, "cmd_"+name[1:])
        else:
            return None

    def assignTo(self, bot):
        self.bot = bot


class Bot:
    def __init__(self, token, admins, handler=None, logger=None, proxy=None):
        self.logger = logger or logging.getLogger(self.__class__.__name__)

        self.token = token
        self.baseUrl = 'https://api.telegram.org/bot%s' % self.token
        self.admins = admins
        self.handlers = []
        if handler is not None:
            self.addHandler(handler)
        self._thread_terminate = False
        self.session = requests.Session()
        if proxy!=None:
            self.session.proxies = { 'https': proxy }

    def addHandler(self, handler):
        if handler is not None:
            handler.assignTo(self)
            self.handlers.append(handler)
        pass

    def process_callback(self, callback):
        self.session.post(
            self.baseUrl + '/answerCallbackQuery',
            {'callback_query_id': callback['id']}
        )
        pass

    def process_updates(self, updates):
        for update in updates:
            if 'callback_query' in update:
                callback = update['callback_query']
                self.process_callback( callback )
                # answer to callback

                message = callback['message']
                message['from'] = callback['from']
                message['text'] = callback['data']
                update.update({'message': message})

            if 'message' in update:
                message = update['message']

                if 'from' in message and 'text' in message:
                    user = message['from']
                    if user['id'] in self.admins:
                        self.logger.info(
                            "request \"%s\" from %d/%s",
                            message['text'],
                            message['from']['id'],
                            message['from']['first_name']
                        )
                        self.exec_command( message )
                else:
                    self.logger.warn("Unauthorized request from %s", json.dumps(user) )

            self.params['offset'] = update['update_id']+1
        return

    def request_loop(self):
        self.params = {'timeout': 60, 'offset': 0, 'limit': 5}
        while not self._thread_terminate:
            try:
                req = self.session.post(
                    self.baseUrl+'/getUpdates',
                    self.params,
                    timeout= self.params['timeout']+5
                )
                result = req.json()
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
            except KeyboardInterrupt, ke:
                return
            except BaseException, e:
                self.logger.exception(
                    'Error while recieve updates from server'
                )
                time.sleep(30)
            pass
        return

    def loop_start(self):
        self._thread = threading.Thread(target=self.request_loop)
        self._thread.daemon = True
        self._thread.start()
        pass

    def loop_stop(self):
        self._thread_terminate = True
        if threading.current_thread() != self._thread:
            self._thread.join()
            self._thread = None
        pass

    def loop_forever(self):
        self.request_loop()
        pass

    def exec_inline(self, message):
        pass

    def exec_command(self, message):
        params = message['text'].lower().split()
        command = params[0]
        self.logger.debug('Processing command %s (%s)', command, ", ".join(params[1:]) )
        ret = None

        for handler in self.handlers:
            functor = handler.getCommand(command)
            if functor:
                try:
                    if 'full_message' in functor.func_code.co_varnames:
                        resp = functor.__call__(full_message=message['text'])
                    else:
                        resp = functor.__call__(*params[1:])
                except BaseException, e:
                    resp = traceback.format_exc()

                if resp is None:
                    return
                if type(resp) != list:
                    resp = [resp]
                for item in resp:
                    self.__send_response(message['chat']['id'], item)
                return

        cmds = []
        for x in self.handlers:
            cmds = cmds + x.commands()
        msg = "Unknown command\n%s" % "\n".join(cmds)
        self.logger.debug( msg )
        self.__send_response(message['chat']['id'], msg)
        pass

    def __send_response(self, to, response):
        if response is None:
            return

        if type(response) == dict:
            self.send_message(to, **response)
        elif type(response) == file:
            self.send_message(to, document=response)
        else:
            self.send_message(to, text=response)
        pass

    def exec_event(self, event_name, *event_data):
        for handler in self.handlers:
            functor = handler.getEvent(event_name)
            if functor:
                try:
                    response = functor.__call__(*event_data)
                except BaseException, e:
                    response = str(e)
                for to in self.admins:
                    self.__send_response(to, response)
                return
        pass

    def send_message_admins( self, **kwargs ):
        for to_chat_id in self.admins:
            self.send_message( to_chat_id, **kwargs )
        return

    def send_request( self, url, method='GET', body=None, files={}, timeout=15 ):
        if method=='GET' and body is None:
           req = self.session.get( url, timeout=timeout )
        else:
           req = self.session.post( url, body, files=files, timeout=timeout )
        result = req.json()
        self.logger.debug('Response: ' + json.dumps(result))
        if result['ok']:
            return
        self.logger.error('Error while send message')
        self.logger.error(result)
        return

    def send_message(
            self, to, text=None, photo=None, video=None,
            audio=None, voice=None, document=None, markup=None, 
	    latitude=None, longitude=None, reply_to_id=None, extra=None):
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

        try:
            self.send_request( self.baseUrl + '/send%s' % (method),
               method = 'POST', body=params, files=files, timeout=10
            )
        except BaseException, e:
            self.logger.exception('Error while send message')
        pass
