FROM aiogram/telegram-bot-api:latest

USER root

RUN apk add --no-cache python3 py3-pip ca-certificates wget

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY . /app/
RUN chmod +x /app/render-entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOCAL_BOT_API_BASE=http://127.0.0.1:8081 \
    LOCAL_BOT_API_CONTAINER_DIR=/var/lib/telegram-bot-api \
    DOWNLOAD_DIR=/tmp/apk-automation-downloads \
    BACKUP_DIR=/tmp/apk-automation-backups \
    LOG_DIR=/tmp/apk-automation-logs

EXPOSE 10000

ENTRYPOINT ["/app/render-entrypoint.sh"]
