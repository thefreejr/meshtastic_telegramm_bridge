from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))
    is_admin = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    message_count = Column(Integer, default=0)
    last_active = Column(DateTime, default=datetime.utcnow)

class Message(Base):
    __tablename__ = 'messages'
    
    id = Column(Integer, primary_key=True)
    direction = Column(String(10))  # 'to_mesh' или 'from_mesh'
    chat_id = Column(Integer)
    mesh_node = Column(String(50))
    content = Column(Text)
    message_type = Column(String(20))  # 'text', 'position', 'command'
    timestamp = Column(DateTime, default=datetime.utcnow)

class MeshNode(Base):
    __tablename__ = 'mesh_nodes'
    
    id = Column(Integer, primary_key=True)
    node_id = Column(String(50), unique=True)
    long_name = Column(String(100))
    short_name = Column(String(50))
    hardware_model = Column(String(50))
    last_seen = Column(DateTime)
    battery_level = Column(Integer)
    latitude = Column(Float)
    longitude = Column(Float)
    altitude = Column(Float)
    message_count = Column(Integer, default=0)

class Database:
    def __init__(self, db_url):
        try:
            self.engine = create_engine(db_url, echo=False)
            Base.metadata.create_all(self.engine)
            Session = sessionmaker(bind=self.engine)
            self.session = Session()
            self.logger = logging.getLogger(__name__)
            self.logger.info(f"Подключение к базе данных: {db_url}")
        except Exception as e:
            self.logger = logging.getLogger(__name__)
            self.logger.error(f"Ошибка подключения к базе данных: {e}")
            raise
    
    def add_user(self, chat_id, username, first_name, last_name, is_admin=False):
        try:
            user = self.session.query(User).filter_by(chat_id=chat_id).first()
            if not user:
                user = User(
                    chat_id=chat_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_admin=is_admin
                )
                self.session.add(user)
                self.session.commit()
                self.logger.info(f"Добавлен новый пользователь: {first_name} (ID: {chat_id})")
            return user
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении пользователя: {e}")
            self.session.rollback()
            raise
    
    def log_message(self, direction, chat_id, content, mesh_node=None, message_type='text'):
        try:
            message = Message(
                direction=direction,
                chat_id=chat_id,
                mesh_node=mesh_node,
                content=content,
                message_type=message_type
            )
            self.session.add(message)
            
            if direction == 'to_mesh':
                user = self.session.query(User).filter_by(chat_id=chat_id).first()
                if user:
                    user.message_count += 1
                    user.last_active = datetime.utcnow()
            
            self.session.commit()
        except Exception as e:
            self.logger.error(f"Ошибка при логировании сообщения: {e}")
            self.session.rollback()
    
    def update_node(self, node_id, node_data):
        try:
            node = self.session.query(MeshNode).filter_by(node_id=node_id).first()
            if not node:
                node = MeshNode(node_id=node_id)
                self.session.add(node)
            
            if 'user' in node_data:
                user_info = node_data['user']
                if isinstance(user_info, dict):
                    node.long_name = user_info.get('longName')
                    node.short_name = user_info.get('shortName')
                    node.hardware_model = user_info.get('hwModel')
            
            if 'position' in node_data:
                pos = node_data['position']
                if isinstance(pos, dict):
                    node.latitude = pos.get('latitude')
                    node.longitude = pos.get('longitude')
                    node.altitude = pos.get('altitude')
            
            if 'deviceMetrics' in node_data:
                metrics = node_data['deviceMetrics']
                if isinstance(metrics, dict):
                    node.battery_level = metrics.get('batteryLevel')
            
            node.last_seen = datetime.utcnow()
            self.session.commit()
            return node
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении узла {node_id}: {e}")
            self.session.rollback()
            raise