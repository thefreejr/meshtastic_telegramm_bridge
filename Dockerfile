FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install -r requirements.txt

# Копирование кода
COPY . .

# Создание директорий
RUN mkdir -p logs storage config

# Точка входа
CMD ["python", "main.py"]