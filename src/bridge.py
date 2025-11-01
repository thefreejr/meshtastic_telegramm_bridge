import logging
import asyncio
import yaml
from typing import Dict, Any
from datetime import datetime
from queue import Queue

from .mqtt_client import MeshtasticMQTTClient
from .telegram_bot import TelegramBot
from .models import Database

class MeshtasticTelegramBridge:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = self._load_config(config_path)
        self._setup_logging()
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("Инициализация Meshtastic-Telegram Bridge...")
        
        # Очередь для передачи сообщений из MQTT в Telegram
        self.message_queue = Queue()
        
        # Инициализация компонентов
        try:
            self.database = Database(self.config.get('database', {}).get('url', 'sqlite:///storage/database.db'))
        except Exception as e:
            self.logger.error(f"Ошибка инициализации базы данных: {e}")
            raise
        
        self.mqtt_client = MeshtasticMQTTClient(self.config)
        self.telegram_bot = TelegramBot(self.config, self.database, self.message_queue)
        
        # Регистрация обработчиков
        self._register_handlers()
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Загрузка конфигурации"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            self.logger.error(f"Конфигурационный файл не найден: {config_path}")
            raise
        except yaml.YAMLError as e:
            self.logger.error(f"Ошибка парсинга YAML: {e}")
            raise
    
    def _setup_logging(self):
        """Настройка логирования"""
        try:
            import os
            os.makedirs('logs', exist_ok=True)
            
            log_level = getattr(logging, self.config.get('bridge', {}).get('log_level', 'INFO').upper())
            
            logging.basicConfig(
                level=log_level,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler('logs/bridge.log', encoding='utf-8'),
                    logging.StreamHandler()
                ]
            )
        except Exception as e:
            # Fallback на базовое логирование
            logging.basicConfig(level=logging.INFO)
            logging.error(f"Ошибка настройки логирования: {e}")
    
    def _register_handlers(self):
        """Регистрация обработчиков событий"""
        # MQTT -> Telegram
        self.mqtt_client.add_message_handler(self._handle_mqtt_message)
        
        # Telegram -> MQTT
        self.telegram_bot.add_message_handler(self._handle_telegram_message)
    
    def _handle_mqtt_message(self, message_type: str, data: Dict, topic: str):
        """Обработка входящих MQTT сообщений"""
        try:
            if message_type == 'text':
                self._handle_text_message(data)
            elif message_type == 'position':
                self._handle_position_message(data)
            elif message_type == 'nodeinfo':
                self._handle_nodeinfo_message(data)
            elif message_type == 'telemetry':
                self._handle_telemetry_message(data)
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки MQTT сообщения: {e}")
    
    def _handle_text_message(self, data: Dict):
        """Обработка текстовых сообщений из Mesh"""
        payload = data.get('payload', {})
        text = payload.get('text', '')
        from_node = data.get('from', 'unknown')
        
        if not text:
            return
        
        # Получение информации об узле
        node_info = f"Узел {from_node}"
        if from_node in self.mqtt_client.mesh_nodes:
            node_data = self.mqtt_client.mesh_nodes[from_node]
            if 'user' in node_data:
                node_info = node_data['user'].get('longName', f"Узел {from_node}")
        
        # Форматирование сообщения для Telegram
        telegram_message = f"📡 {node_info}: {text}"
        
        # Добавление сообщения в очередь для отправки в Telegram
        self.message_queue.put(('broadcast', telegram_message))
        
        # Логирование
        try:
            self.database.log_message('from_mesh', 0, text, from_node)
        except Exception as e:
            self.logger.error(f"Ошибка логирования сообщения: {e}")
        
        self.logger.info(f"Сообщение из Mesh: {from_node} -> {text}")
    
    def _handle_position_message(self, data: Dict):
        """Обработка позиционных сообщений"""
        payload = data.get('payload', {})
        from_node = data.get('from', 'unknown')
        
        lat = payload.get('latitude')
        lon = payload.get('longitude')
        alt = payload.get('altitude', 0)
        
        if lat and lon:
            # Обновление информации об узле
            self.database.update_node(from_node, {'position': payload})
            
            # Форматирование сообщения для Telegram
            position_message = (
                f"📍 Позиция от {from_node}:\n"
                f"Широта: {lat:.6f}\n"
                f"Долгота: {lon:.6f}\n"
                f"Высота: {alt:.0f} м"
            )
            
            # Отправка в Telegram (только админам) через очередь
            self.message_queue.put(('notify_admins', position_message))
            
            self.logger.info(f"Позиция от {from_node}: {lat}, {lon}")
    
    def _handle_nodeinfo_message(self, data: Dict):
        """Обработка информации об узле"""
        from_node = data.get('from', 'unknown')
        payload = data.get('payload', {})
        
        # Сохранение информации об узле в mesh_nodes
        if from_node not in self.mqtt_client.mesh_nodes:
            self.mqtt_client.mesh_nodes[from_node] = {}
        self.mqtt_client.mesh_nodes[from_node]['user'] = payload.get('user', {})
        
        # Обновление информации об узле в БД
        try:
            self.database.update_node(from_node, {'user': payload})
        except Exception as e:
            self.logger.error(f"Ошибка обновления информации об узле: {e}")
        
        user_info = payload.get('user', {})
        long_name = user_info.get('longName', from_node)
        
        self.logger.info(f"Информация об узле: {long_name} ({from_node})")
    
    def _handle_telemetry_message(self, data: Dict):
        """Обработка телеметрии"""
        from_node = data.get('from', 'unknown')
        payload = data.get('payload', {})
        
        battery_level = payload.get('batteryLevel')
        voltage = payload.get('voltage')
        
        if battery_level and battery_level < 20:
            # Уведомление о низком заряде батареи через очередь
            warning_message = f"⚠️ Низкий заряд батареи у {from_node}: {battery_level}%"
            self.message_queue.put(('notify_admins', warning_message))
        
        # Обновление телеметрии в БД
        try:
            self.database.update_node(from_node, {'deviceMetrics': payload})
        except Exception as e:
            self.logger.error(f"Ошибка обновления телеметрии: {e}")
    
    
    def _handle_telegram_message(self, action: str, data: Dict):
        """Обработка сообщений из Telegram"""
        if action == 'send_text':
            self.mqtt_client.send_text_message(data['text'])
        elif action == 'send_position':
            self.mqtt_client.send_position(data['lat'], data['lon'])
    
    def run(self):
        """Запуск моста"""
        self.logger.info("Запуск Meshtastic-Telegram Bridge...")
        
        try:
            # Подключение к MQTT
            self.mqtt_client.connect()
            
            # Запуск Telegram бота (блокирующий, но с обработкой очереди)
            self.telegram_bot.run()
            
        except KeyboardInterrupt:
            self.logger.info("Получен сигнал прерывания...")
        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}", exc_info=True)
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Корректное завершение работы"""
        self.logger.info("Завершение работы...")
        try:
            self.mqtt_client.disconnect()
        except Exception as e:
            self.logger.error(f"Ошибка при отключении от MQTT: {e}")
        try:
            self.database.session.close()
        except Exception as e:
            self.logger.error(f"Ошибка при закрытии БД: {e}")