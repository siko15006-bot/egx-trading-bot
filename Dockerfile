FROM python:3.11-slim

WORKDIR /app
COPY requirements_webhook.txt .
RUN pip install --no-cache-dir -r requirements_webhook.txt
COPY . .

EXPOSE 5000
CMD ["python", "tv_webhook_server.py"]
