from tornado.ioloop import IOLoop, PeriodicCallback
import paho.mqtt.client as mqtt
import logging
import base64
import os

class TornadoMqttClient(object):
    def __init__(self, ioloop=None, clean_session=True, clientid=None, host='localhost', port=1883, keepalive=60, username=None, password=None):
        self.ioloop = ioloop or IOLoop.current()

        self._client =  mqtt.Client(client_id=clientid or self._genid(), clean_session=clean_session)
        if username!=None:
            self._client.username_pw_set(self._username, self._password)   

        self._client.on_connect = self.on_mqtt_connect
        self._client.on_message = self.on_mqtt_message
        self.host = host
        self.port = port
        self.keepalive = keepalive
        pass

    def _genid(self):
        return base64.urlsafe_b64encode(os.urandom(32)).replace('=', 'e')
    
    def start(self):
        logging.info("Start connect to mqtt broker")
        self._client.connect(self.host, self.port, self.keepalive)
        self._start_ioloop()
        pass

    def on_mqtt_connect(self, client, userdata, flags, rc ):
        logging.info("MQTT broker: %s", mqtt.connack_string(rc))
        pass

    def on_mqtt_message(self, client, userdata, msg):
        pass

    def _start_ioloop(self):
        self._sock = self._client.socket()
        self.ioloop.add_handler(self._sock.fileno(), self._handle_read, IOLoop.READ )
        self.ioloop.add_handler(self._client._sockpairR.fileno(), self._handle_write, IOLoop.READ )
        
        self._sheduler = PeriodicCallback(callback=self._client.loop_misc, callback_time=10000)
        self._sheduler.start()
        pass

    def _handle_write(self, fd, events):
        if events & IOLoop.READ:
            self._client._sockpairR.recv(1)
            rc = self._client.loop_write() 

    def _handle_read(self, fd, events):
        if events & IOLoop.READ:
            rc = self._client.loop_read() 
