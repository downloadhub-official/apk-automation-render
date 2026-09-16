#!/bin/sh
set -eu

# Render Cloud Test startup only.
# Production is not referenced or used by this container.

: "${TELEGRAM_API_ID:?TELEGRAM_API_ID is required}"
: "${TELEGRAM_API_HASH:?TELEGRAM_API_HASH is required}"
: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN is required}"
: "${RENDER_EXTERNAL_URL:?RENDER_EXTERNAL_URL is required}"
: "${WEBHOOK_SECRET:?WEBHOOK_SECRET is required}"

TELEGRAM_WORK_DIR="/var/lib/telegram-bot-api"
TELEGRAM_TEMP_DIR="${TELEGRAM_WORK_DIR}/temp"

mkdir -p \
  "${TELEGRAM_WORK_DIR}" \
  "${TELEGRAM_TEMP_DIR}" \
  /tmp/apk-automation-downloads \
  /tmp/apk-automation-backups \
  /tmp/apk-automation-logs

# The upstream Docker image changes the work directory ownership to the
# telegram-bot-api user. Keep the temporary directory inside that same
# writable tree instead of using /tmp/telegram-bot-api.
chown -R telegram-bot-api:telegram-bot-api "${TELEGRAM_WORK_DIR}"
chmod 750 "${TELEGRAM_WORK_DIR}"
chmod 750 "${TELEGRAM_TEMP_DIR}"

export TELEGRAM_WORK_DIR
export TELEGRAM_TEMP_DIR
export TELEGRAM_LOCAL=1
export TELEGRAM_HTTP_PORT=8081
export TELEGRAM_HTTP_IP_ADDRESS=127.0.0.1

API_LOG="/tmp/telegram-bot-api.log"
rm -f "${API_LOG}"

echo "Starting Telegram Local Bot API..."
echo "Telegram work dir: ${TELEGRAM_WORK_DIR}"
echo "Telegram temp dir: ${TELEGRAM_TEMP_DIR}"
echo "Telegram HTTP: 127.0.0.1:8081"

# Start the binary directly. This avoids the base image wrapper's separate
# /tmp permission assumption and makes the exact startup arguments explicit.
telegram-bot-api \
  --api-id="${TELEGRAM_API_ID}" \
  --api-hash="${TELEGRAM_API_HASH}" \
  --local \
  --dir="${TELEGRAM_WORK_DIR}" \
  --temp-dir="${TELEGRAM_TEMP_DIR}" \
  --http-port=8081 \
  --http-ip-address=127.0.0.1 \
  --username=telegram-bot-api \
  --groupname=telegram-bot-api \
  >"${API_LOG}" 2>&1 &
API_PID=$!

cleanup() {
  kill "${API_PID}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# Do not probe /. Telegram Bot API's root path is not a Bot API method and
# normally returns 404. Probe the real getMe method instead.
i=0
while :; do
  if response=$(wget -q -O - "http://127.0.0.1:8081/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null); then
    case "${response}" in
      *'"ok":true'*)
        echo "Telegram Local Bot API is ready."
        break
        ;;
    esac
  fi

  if ! kill -0 "${API_PID}" 2>/dev/null; then
    echo "ERROR: Telegram Local Bot API exited during startup." >&2
    cat "${API_LOG}" >&2 || true
    exit 1
  fi

  i=$((i + 1))
  if [ "${i}" -ge 120 ]; then
    echo "ERROR: Telegram Local Bot API did not become ready within 120 seconds." >&2
    cat "${API_LOG}" >&2 || true
    exit 1
  fi
  sleep 1
done

echo "Starting Render webhook bot..."
exec python3 /app/main.py
