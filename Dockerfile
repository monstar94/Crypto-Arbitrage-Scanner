# Используем минимальный Python-образ
FROM python:3.9-slim

# Установить системные зависимости (включая libGL и другие необходимые библиотеки)
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && apt-get clean

# Устанавливаем директорию для приложения
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt /app/

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта
COPY . /app

# Команда запуска приложения
CMD ["python", "direct_arbitrage.py"]
