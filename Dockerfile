FROM python:3.12-slim

WORKDIR /app

# Устанавливаем зависимости отдельно для кэширования слоёв
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# База данных хранится в /data (можно смонтировать volume)
ENV DATABASE_PATH=/data/fairdick.db
VOLUME ["/data"]

CMD ["python", "main.py"]
