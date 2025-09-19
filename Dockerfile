#FROM python:3.9-slim
FROM python:3.9-slim-bullseye

WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir --progress-bar off -r requirements.txt

# Копируем код приложения
COPY ./app ./app

# Запуск Uvicorn с одним воркером
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--reload"]
