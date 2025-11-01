import json
import logging
import paho.mqtt.client as mqtt
from typing import Callable, Dict, Any
import ssl

class MeshtasticMQTTClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.message_handlers = []
        self.mesh_nodes: Dict[str, Dict[str, Any]] = {}  # Хранение информации об узлах
        
        # MQTT клиент
        self.client = mqtt.Client(client_id=config['mqtt']['client_id'])
        
        # Аутентификация
        if config['mqtt'].get('username'):
            self.client.username_pw_set(
                config['mqtt']['username'], 
                config['mqtt'].get('password')
            )
        
        # TLS/SSL
        if config['mqtt'].get('use_tls', False):
            ssl_context = ssl.create_default_context()
            if config['mqtt'].get('ca_cert'):
                ssl_context.load_verify_locations(config['mqtt']['ca_cert'])
            self.client.tls_set_context(ssl_context)
        
        # Callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe
        self.client.on_disconnect = self._on_disconnect
    
    def add_message_handler(self, handler: Callable):
        """Добавление обработчика сообщений"""
        self.message_handlers.append(handler)
    
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.logger.info("Успешное подключение к MQTT брокеру")
            # Подписка на топики
            for topic in self.config['mqtt']['topics']['subscribe']:
                client.subscribe(topic)
                self.logger.debug(f"Подписан на топик: {topic}")
        else:
            self.logger.error(f"Ошибка подключения к MQTT: {rc}")
    
    def _on_subscribe(self, client, userdata, mid, granted_qos):
        self.logger.debug(f"Успешная подписка (mid: {mid})")
    
    def _on_message(self, client, userdata, msg):
        try:
            self.logger.debug(f"Получено MQTT сообщение: {msg.topic}")
            
            # Парсинг JSON
            data = json.loads(msg.payload.decode('utf-8'))
            
            # Определение типа сообщения
            message_type = self._get_message_type(msg.topic, data)
            
            # Вызов обработчиков
            for handler in self.message_handlers:
                try:
                    handler(message_type, data, msg.topic)
                except Exception as e:
                    self.logger.error(f"Ошибка в обработчике сообщений: {e}")
                    
        except json.JSONDecodeError as e:
            self.logger.error(f"Ошибка парсинга JSON: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка обработки MQTT сообщения: {e}")
    
    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            self.logger.warning("Неожиданное отключение от MQTT брокера")
        else:
            self.logger.info("Отключение от MQTT брокера")
    
    def _get_message_type(self, topic: str, data: Dict) -> str:
        """Определение типа сообщения"""
        if 'text' in topic or data.get('type') == 'sendtext':
            return 'text'
        elif 'position' in topic or data.get('type') == 'position':
            return 'position'
        elif 'telemetry' in topic:
            return 'telemetry'
        elif 'nodeinfo' in topic:
            return 'nodeinfo'
        else:
            return 'unknown'
    
    def send_text_message(self, text: str, destination: str = "^all"):
        """Отправка текстового сообщения в Mesh"""
        try:
            message = {
                "type": "sendtext",
                "text": text,
                "destination": destination,
                "channel": 0
            }
            
            topic = self.config['mqtt']['topics']['publish']
            result = self.client.publish(topic, json.dumps(message))
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.logger.info(f"Отправлено сообщение в Mesh: {text}")
            else:
                self.logger.error(f"Ошибка отправки сообщения в Mesh: код {result.rc}")
        except Exception as e:
            self.logger.error(f"Ошибка при отправке текстового сообщения: {e}")
    
    def send_position(self, lat: float, lon: float, alt: int = 0):
        """Отправка позиции в Mesh"""
        try:
            message = {
                "type": "position",
                "latitude": lat,
                "longitude": lon,
                "altitude": alt
            }
            
            topic = self.config['mqtt']['topics']['publish']
            result = self.client.publish(topic, json.dumps(message))
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.logger.info(f"Отправлена позиция: {lat}, {lon}")
            else:
                self.logger.error(f"Ошибка отправки позиции в Mesh: код {result.rc}")
        except Exception as e:
            self.logger.error(f"Ошибка при отправке позиции: {e}")
    
    def connect(self):
        """Подключение к MQTT брокеру"""
        try:
            self.client.connect(
                self.config['mqtt']['host'],
                self.config['mqtt']['port'],
                60
            )
            self.client.loop_start()
        except Exception as e:
            self.logger.error(f"Ошибка подключения к MQTT: {e}")
            raise
    
    def disconnect(self):
        """Отключение от MQTT брокера"""
        self.client.loop_stop()
        self.client.disconnect()