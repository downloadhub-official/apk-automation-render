from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.routing import Route
from starlette.requests import Request

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from app.workflow import WorkflowError, run_workflow
from app.telegram_local import copy_local_bot_api_file

LOG_DIR = Path(config.LOG_DIR)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("apk-bot")


def allowed_chat(update: Update) -> bool:
    if config.ALLOWED_CHAT_ID is None:
        return True
    chat = update.effective_chat
    return bool(chat and chat.id == int(config.ALLOWED_CHAT_ID))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update):
        return
    await update.message.reply_text(
        "✅ Render Cloud APK Automation Bot is online.\n\n"
        "শুধু APK document পাঠান। Filename দেখে app শনাক্ত করে "
        "GitHub Release + short links + Blogger update করা হবে."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update):
        return
    await update.message.reply_text(
        "🟢 Render Cloud Bot is running.\n"
        f"GitHub Test Repository: {config.GITHUB_OWNER}/{config.GITHUB_REPO}\n"
        f"Webhook: {config.RENDER_EXTERNAL_URL}{config.WEBHOOK_PATH}"
    )


async def _process_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update):
        return

    message = update.message
    document = message.document if message else None
    if not document:
        return

    filename = document.file_name or "unnamed.apk"
    if not filename.lower().endswith(".apk"):
        await message.reply_text(
            "❌ ERROR\n\nএটি APK file নয়। শুধুমাত্র .apk document পাঠান."
        )
        return

    await message.reply_text(
        f"📥 APK received: `{filename}`\n"
        "Cloud automation শুরু হচ্ছে...",
        parse_mode="Markdown",
    )

    download_dir = Path(config.DOWNLOAD_DIR)
    download_dir.mkdir(parents=True, exist_ok=True)
    local_apk = download_dir / Path(filename).name

    try:
        await message.reply_text(
            "📥 STEP 1/7 — Downloading APK from Telegram Local Bot API..."
        )
        tg_file = await context.bot.get_file(
            document.file_id,
            read_timeout=None,
            connect_timeout=None,
            pool_timeout=None,
        )
        source_path, copied_size = await asyncio.to_thread(
            copy_local_bot_api_file,
            tg_file,
            local_apk,
        )
        logger.info(
            "Telegram Local API file copied: source=%s destination=%s size=%d",
            source_path,
            local_apk,
            copied_size,
        )
    except Exception as exc:
        logger.exception("Telegram download failed")
        local_apk.unlink(missing_ok=True)
        await message.reply_text(
            "❌ TELEGRAM DOWNLOAD ERROR\n\n"
            f"{exc}\n\nGitHub/Blogger were not changed."
        )
        return

    if not local_apk.exists():
        await message.reply_text(
            "❌ TELEGRAM DOWNLOAD ERROR\n\n"
            "The Local Bot API reported success but the working APK file was not found."
        )
        return

    if config.MAX_APK_BYTES and local_apk.stat().st_size > config.MAX_APK_BYTES:
        from app.utils import human_bytes

        size = local_apk.stat().st_size
        local_apk.unlink(missing_ok=True)
        await message.reply_text(
            "❌ FILE SIZE ERROR\n\n"
            f"APK size: {human_bytes(size)}\n"
            f"Configured maximum: {human_bytes(config.MAX_APK_BYTES)}"
        )
        return

    loop = asyncio.get_running_loop()

    def report_sync(text: str):
        future = asyncio.run_coroutine_threadsafe(
            message.reply_text(text),
            loop,
        )
        try:
            future.result()
        except Exception:
            logger.exception("Could not send progress report")

    try:
        result = await asyncio.to_thread(
            run_workflow,
            filename,
            local_apk,
            report_sync,
        )
        await message.reply_text(result)
    except WorkflowError as exc:
        logger.exception("Workflow failed")
        await message.reply_text(str(exc))
    except Exception:
        logger.exception("Unexpected workflow failure")
        local_apk.unlink(missing_ok=True)
        await message.reply_text(
            "❌ FATAL ERROR\n\n"
            "Unexpected error occurred. Check Render logs."
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Acknowledge the webhook quickly, then process the APK in the background.

    This is important for large APKs: Telegram's webhook request must not stay
    open while a 200-400 MB file is being copied/uploaded.
    """
    if not allowed_chat(update):
        return

    context.application.create_task(
        _process_document(update, context),
        update=update,
        name=f"apk-job-{update.update_id}",
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update):
        return
    await update.message.reply_text(
        "ℹ️ APK file/document পাঠান। Filename থেকেই app শনাক্ত হবে."
    )


def build_application() -> Application:
    if not config.TELEGRAM_BOT_TOKEN or "PASTE_" in config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

    base = config.LOCAL_BOT_API_BASE.rstrip("/")

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .updater(None)
        .base_url(base + "/bot")
        .base_file_url(base + "/file/bot")
        .local_mode(True)
        .read_timeout(None)
        .write_timeout(None)
        .connect_timeout(None)
        .pool_timeout(None)
        .media_write_timeout(None)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app


application = build_application()


async def health(_: Request):
    return PlainTextResponse("ok")


async def telegram_webhook(request: Request):
    expected = config.WEBHOOK_SECRET
    if expected:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if supplied != expected:
            return PlainTextResponse("forbidden", status_code=403)

    try:
        payload = await request.json()
        update = Update.de_json(payload, bot=application.bot)
        if update is None:
            return PlainTextResponse("bad update", status_code=400)

        await application.update_queue.put(update)
        return PlainTextResponse("ok")
    except Exception:
        logger.exception("Could not accept Telegram webhook update")
        return PlainTextResponse("bad request", status_code=400)


async def post_init(app: Application):
    webhook_url = config.RENDER_EXTERNAL_URL.rstrip("/") + config.WEBHOOK_PATH
    await app.bot.set_webhook(
        url=webhook_url,
        secret_token=config.WEBHOOK_SECRET or None,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        max_connections=40,
    )
    logger.info("Telegram webhook set to %s", webhook_url)


async def runner():
    if not config.RENDER_EXTERNAL_URL:
        raise RuntimeError("RENDER_EXTERNAL_URL is required for the Telegram webhook.")
    if not config.WEBHOOK_SECRET:
        raise RuntimeError("WEBHOOK_SECRET is required for the Telegram webhook.")

    async with application:
        await post_init(application)
        await application.start()

        starlette = Starlette(
            routes=[
                Route("/health", health, methods=["GET"]),
                Route(config.WEBHOOK_PATH, telegram_webhook, methods=["POST"]),
            ]
        )

        port = int(os.getenv("PORT", "10000"))
        server = uvicorn.Server(
            uvicorn.Config(
                starlette,
                host="0.0.0.0",
                port=port,
                log_level="info",
                proxy_headers=True,
            )
        )

        logger.info("Render public webhook server listening on 0.0.0.0:%d", port)
        await server.serve()
        await application.stop()


if __name__ == "__main__":
    asyncio.run(runner())
