#!/usr/bin/env python3
"""
Meshtastic-Telegram Bridge
Мост между Mesh сетью Meshtastic и Telegram через MQTT
"""

import os

from src.bridge import MeshtasticTelegramBridge

def main():
    """Основная функция"""
    # Создание необходимых директорий
    os.makedirs('logs', exist_ok=True)
    os.makedirs('storage', exist_ok=True)
    os.makedirs('config', exist_ok=True)
    
    # Запуск моста
    bridge = MeshtasticTelegramBridge()
    bridge.run()

if __name__ == "__main__":
    main()