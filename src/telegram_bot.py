import logging
import asyncio
from queue import Queue, Empty
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    ContextTypes, filters, CallbackContext
)
from typing import Dict, Any, Callable, List, Optional
from .models import User, Message, MeshNode

class TelegramBot:
    def __init__(self, config: Dict[str, Any], database, message_queue: Optional[Queue] = None):
        self.config = config
        self.database = database
        self.message_queue = message_queue
        self.logger = logging.getLogger(__name__)
        
        # Инициализация бота
        self.application = Application.builder().token(config['telegram']['token']).build()
        
        # Обработчики внешних сообщений
        self.message_handlers = []
        
        # Регистрация команд
        self._register_handlers()
    
    def add_message_handler(self, handler: Callable):
        """Добавление обработчика для отправки сообщений в Telegram"""
        self.message_handlers.append(handler)
    
    def _register_handlers(self):
        """Регистрация обработчиков команд"""
        handlers = [
            CommandHandler("start", self._start_command),
            CommandHandler("help", self._help_command),
            CommandHandler("nodes", self._nodes_command),
            CommandHandler("stats", self._stats_command),
            CommandHandler("location", self._location_command),
            CommandHandler("admin", self._admin_command),
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._text_message),
            MessageHandler(filters.LOCATION, self._location_message)
        ]
        
        for handler in handlers:
            self.application.add_handler(handler)
        
        # Настройка меню команд
        self.application.post_init = self._set_commands
        
        # Настройка обработки очереди сообщений после инициализации
        if self.message_queue:
            async def post_init_with_queue(application):
                await self._set_commands(application)
                # Инициализация job_queue для обработки очереди
                application.job_queue.run_repeating(
                    self._process_message_queue, 
                    interval=1.0, 
                    first=1.0
                )
            self.application.post_init = post_init_with_queue
    
    async def _set_commands(self, application):
        """Настройка меню команд"""
        commands = [
            BotCommand("start", "Запустить бота"),
            BotCommand("help", "Помощь"),
            BotCommand("nodes", "Список узлов"),
            BotCommand("stats", "Статистика"),
            BotCommand("location", "Отправить местоположение"),
        ]
        await application.bot.set_my_commands(commands)
    
    async def _process_message_queue(self, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщений из очереди"""
        if not self.message_queue:
            return
        
        try:
            while True:
                try:
                    action, message = self.message_queue.get_nowait()
                    
                    if action == 'broadcast':
                        await self.broadcast_message(message)
                    elif action == 'notify_admins':
                        await self._notify_admins(message)
                    
                except Empty:
                    break
        except Exception as e:
            self.logger.error(f"Ошибка обработки очереди сообщений: {e}")
    
    async def _notify_admins(self, message: str):
        """Уведомление администраторов"""
        for admin_id in self.config['telegram']['admin_ids']:
            try:
                await self.send_message(admin_id, message)
            except Exception as e:
                self.logger.error(f"Ошибка уведомления администратора {admin_id}: {e}")
    
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        # Проверка доступа
        if not self._check_access(chat_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        # Добавление/обновление пользователя
        is_admin = chat_id in self.config['telegram']['admin_ids']
        self.database.add_user(chat_id, user.username, user.first_name, user.last_name, is_admin)
        
        await update.message.reply_text(self.config['telegram']['welcome_message'])
        self.database.log_message('command', chat_id, '/start')
    
    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        help_text = """
🤖 **Meshtastic-Telegram Bridge**

**Основные команды:**
/start - Начать работу с ботом
/help - Показать эту справку
/nodes - Список активных узлов сети
/stats - Статистика моста
/location - Отправить ваше местоположение

**Использование:**
- Просто отправьте текстовое сообщение, и оно будет переслано в Mesh-сеть
- Отправьте местоположение через вложение → Location

**Формат сообщений:**
Сообщения из Telegram: 📱 Имя: Текст
Сообщения из Mesh: 📡 Узел: Текст
        """
        await update.message.reply_text(help_text)
        self.database.log_message('command', update.effective_chat.id, '/help')
    
    async def _nodes_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /nodes"""
        try:
            nodes = self.database.session.query(MeshNode).all()
        except Exception as e:
            self.logger.error(f"Ошибка при получении списка узлов: {e}")
            await update.message.reply_text("❌ Ошибка при получении данных об узлах")
            return
        
        if not nodes:
            await update.message.reply_text("❌ Нет данных об узлах сети")
            return
        
        nodes_text = "📡 **Активные узлы сети:**\n\n"
        
        for node in nodes[:10]:  # Ограничиваем вывод
            nodes_text += f"• **{node.long_name or node.node_id}**\n"
            if node.hardware_model:
                nodes_text += f"  📟 {node.hardware_model}\n"
            if node.battery_level:
                nodes_text += f"  🔋 {node.battery_level}%\n"
            if node.last_seen:
                from datetime import datetime
                try:
                    last_seen = (datetime.utcnow() - node.last_seen).total_seconds() / 60
                    nodes_text += f"  ⏱ {last_seen:.0f} мин назад\n"
                except Exception:
                    nodes_text += f"  ⏱ Данные недоступны\n"
            nodes_text += "\n"
        
        if len(nodes) > 10:
            nodes_text += f"\n... и еще {len(nodes) - 10} узлов"
        
        await update.message.reply_text(nodes_text)
        self.database.log_message('command', update.effective_chat.id, '/nodes')
    
    async def _stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stats"""
        try:
            # Статистика сообщений
            to_mesh = self.database.session.query(Message).filter_by(direction='to_mesh').count()
            from_mesh = self.database.session.query(Message).filter_by(direction='from_mesh').count()
            
            # Статистика пользователей
            total_users = self.database.session.query(User).count()
            active_users = self.database.session.query(User).filter(
                User.last_active != None
            ).count()
            
            # Статистика узлов
            total_nodes = self.database.session.query(MeshNode).count()
        except Exception as e:
            self.logger.error(f"Ошибка при получении статистики: {e}")
            await update.message.reply_text("❌ Ошибка при получении статистики")
            return
        
        stats_text = f"""
📊 **Статистика моста**

👥 **Пользователи:**
   Всего: {total_users}
   Активных: {active_users}

📨 **Сообщения:**
   ➡️ В Mesh: {to_mesh}
   ⬅️ Из Mesh: {from_mesh}
   Всего: {to_mesh + from_mesh}

📡 **Узлы сети:**
   Всего: {total_nodes}
        """
        
        await update.message.reply_text(stats_text)
        self.database.log_message('command', update.effective_chat.id, '/stats')
    
    async def _location_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /location"""
        await update.message.reply_text(
            "📍 Отправьте ваше местоположение через вложение (Attachment) → Location"
        )
    
    async def _admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /admin"""
        chat_id = update.effective_chat.id
        try:
            user = self.database.session.query(User).filter_by(chat_id=chat_id).first()
        except Exception as e:
            self.logger.error(f"Ошибка при проверке прав администратора: {e}")
            await update.message.reply_text("❌ Ошибка при проверке прав")
            return
        
        if not user or not user.is_admin:
            await update.message.reply_text("❌ Недостаточно прав")
            return
        
        admin_text = """
🛠 **Панель администратора**

Доступные команды:
• /stats - детальная статистика
• /nodes - список всех узлов

Статус системы:
• MQTT: ✅ Активно
• База данных: ✅ Активно
• Telegram: ✅ Активно
        """
        
        await update.message.reply_text(admin_text)
    
    async def _text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        chat_id = update.effective_chat.id
        text = update.message.text
        
        if not self._check_access(chat_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        # Форматирование сообщения
        user = update.effective_user
        sender_name = user.first_name or user.username or "Unknown"
        formatted_text = self.config['bridge']['message_format'].format(
            user=sender_name,
            message=text
        )
        
        # Ограничение длины
        max_len = self.config['bridge']['max_message_length']
        if len(formatted_text) > max_len:
            formatted_text = formatted_text[:max_len-3] + "..."
            await update.message.reply_text("⚠️ Сообщение обрезано")
        
        # Отправка через обработчики
        for handler in self.message_handlers:
            try:
                handler('send_text', {'text': formatted_text})
            except Exception as e:
                self.logger.error(f"Ошибка в обработчике отправки: {e}")
        
        await update.message.reply_text("✅ Сообщение отправлено в Mesh-сеть")
        self.database.log_message('to_mesh', chat_id, text)
    
    async def _location_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщений с местоположением"""
        chat_id = update.effective_chat.id
        
        if not self._check_access(chat_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        if not self.config['bridge']['enable_position_sharing']:
            await update.message.reply_text("❌ Отправка местоположения отключена")
            return
        
        location = update.message.location
        lat = location.latitude
        lon = location.longitude
        
        # Отправка через обработчики
        for handler in self.message_handlers:
            try:
                handler('send_position', {'lat': lat, 'lon': lon})
            except Exception as e:
                self.logger.error(f"Ошибка в обработчике отправки позиции: {e}")
        
        await update.message.reply_text(
            f"✅ Местоположение отправлено!\n"
            f"📍 Широта: {lat:.6f}\n"
            f"📍 Долгота: {lon:.6f}"
        )
        self.database.log_message('to_mesh', chat_id, f"POSITION: {lat}, {lon}", message_type='position')
    
    def _check_access(self, chat_id: int) -> bool:
        """Проверка доступа пользователя"""
        allowed_chats = self.config['telegram'].get('allowed_chats', [])
        
        # Если список пустой - разрешены все
        if not allowed_chats:
            return True
        
        return chat_id in allowed_chats
    
    async def send_message(self, chat_id: int, text: str):
        """Отправка сообщения в Telegram"""
        try:
            await self.application.bot.send_message(chat_id=chat_id, text=text)
            self.logger.debug(f"Сообщение отправлено в Telegram chat {chat_id}")
        except Exception as e:
            self.logger.error(f"Ошибка отправки в Telegram: {e}")
    
    async def broadcast_message(self, text: str):
        """Широковещательная отправка сообщения всем пользователям"""
        try:
            users = self.database.session.query(User).all()
        except Exception as e:
            self.logger.error(f"Ошибка при получении списка пользователей: {e}")
            return
        
        for user in users:
            try:
                await self.send_message(user.chat_id, text)
            except Exception as e:
                self.logger.error(f"Ошибка отправки пользователю {user.chat_id}: {e}")
    
    def run(self):
        """Запуск бота"""
        self.logger.info("Запуск Telegram бота...")
        self.application.run_polling()