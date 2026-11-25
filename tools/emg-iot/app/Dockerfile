FROM python:3.12-slim
RUN pip install --no-cache-dir paho-mqtt==2.1.0 "psycopg[binary]==3.1.19"
WORKDIR /app
COPY ingest.py publish.py schema.py alerts.py ./
