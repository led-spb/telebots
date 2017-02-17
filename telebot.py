import requests, logging, json, time
import threading

class BotRequestHandler:

      def commands(self):
          return ['/'+x[4:] for x in dir(self) if x.find('cmd_')==0]

      def getEvent(self,name):
          if hasattr(self,"event_"+name):
             return getattr(self, "event_"+name )
          else:
             return None

      def getCommand(self, name):
          if name.find('/')==0 and hasattr(self,"cmd_"+name[1:]):
             return getattr(self, "cmd_"+name[1:] )
          else:
             return None

      def assignTo(self, bot):
          self.bot = bot


class Bot:
      def __init__(self, token, admins, handler, logger=None ):
          self.logger = logger or logging.getLogger(self.__class__.__name__)

          self.token  = token
          self.admins = admins

          self.handler = handler
          self.handler.assignTo(self)
          self._thread_terminate = False


      def request_loop(self):
          params = { 'timeout':60, 'offset': 0, 'limit': 5 }
          while not self._thread_terminate:
             try:
               req = requests.post( 'https://api.telegram.org/bot%s/getUpdates' % self.token, params, timeout=60+5 )
               result = req.json()
               self.logger.debug( 'got:'+json.dumps(result) )

               if result['ok']:
                  updates = result['result']
                  for update in updates:

                      if 'callback_query' in update:
                         callback = update['callback_query']
                         # answer to callback
                         requests.post('https://api.telegram.org/bot%s/answerCallbackQuery' % self.token, {'callback_query_id': callback['id']} )

                         message = callback['message']
                         message['from'] = callback['from']
                         message['text'] = callback['data']
                         update.update( {'message': message } )



                      if 'message' in update:
                         message = update['message']

                         if 'from' in message and 'text' in message:
                            user = message['from']
                            if user['id'] in self.admins:
                               self.logger.info("request \"%s\" from %d/%s", message['text'], message['from']['id'], message['from']['first_name'] )
                               self.exec_command( message )

                      params['offset'] = update['update_id']+1
               else:
                 self.logger.error('Error while recieve updates from server')
                 self.logger.error(result)
             except BaseException, e:
                self.logger.exception('Error while recieve updates from server')
                time.sleep(30)
             pass
          return

      def loop_start(self):
          self._thread = threading.Thread( target=self.request_loop )
          self._thread.daemon = True
          self._thread.start()
          pass

      def loop_stop(self):
          self._thread_terminate = True
          if threading.current_thread() != self._thread:
             self._thread.join()
             self._thread = None
          pass

      def exec_command(self, message):
          params = message['text'].lower().split()
          command = params[0]
          ret = None

          f = self.handler.getCommand(command)
          if f:
             try:
               response = f.__call__(*params[1:])
             except BaseException,e:
               response = str(e)

             self.__send_response( message['chat']['id'], response )
             return
  
          cmds = self.handler.commands()
          msg = "Unknown command\n%s" % "\n".join(cmds)
          self.__send_response( message['chat']['id'], msg )
          pass

      def __send_response(self, to, response):
          if response==None:
             return 

          if type(response)==dict:
             self.send_message( to, **response )
          elif type(response)==file:
             self.send_message( to, document=response )
          else:
             self.send_message( to, text=response )
          pass

      def exec_event( self, event_name, *event_data ):
          f = self.handler.getEvent(event_name)
          if f:
             try:
               response = f.__call__( *event_data )
             except BaseException,e:
               response = str(e)

             for to in self.admins:
                 self.__send_response( to, response )
          pass


      def send_message( self, to, text=None, photo=None, video=None, audio=None, voice=None, document=None, markup=None, reply_to_id=None, extra=None ):
          params = { 'chat_id': to }
          files = {}

          if photo!=None:
             method = 'Photo'
             files['photo'] = photo
          elif voice!=None:
             method = 'Voice'
             files['voice'] = voice
          elif audio!=None:
             method = 'Audio'
             files['audio'] = audio
          elif video!=None:
             method = 'Video'
             files['video'] = video
          elif document!=None:
             method = 'Document'
             files['document'] = document
          else:
             method = 'Message'
             params['text'] = text

          if markup!=None:
             params['reply_markup'] = json.dumps( markup )
          if reply_to_id!=None:
             params['reply_to_message_id'] = reply_to_id

          if extra!=None:
             for key,val in extra.iteritems():
                 params[key] = val

          try:
            req = requests.post( 'https://api.telegram.org/bot%s/send%s' % (self.token,method), params, files=files, timeout=4 )
            result = req.json()
            self.logger.debug('Response: '+json.dumps(result) )
            if result['ok']:
               return
            self.logger.error('Error while send message')
            self.logger.error(result)
          except BaseException, e:
            self.logger.exception('Error while send message')
          pass
