import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from telegram import Update

from worker.bot.telegram_bot import (
    ask_category_confirmation,
    get_application,
    notify_unknown_account,
    send_large_amount_confirmation,
    send_message,
)
from worker.config import POLL_INTERVAL_MINUTES, TELEGRAM_WEBHOOK_URL
from worker.integrations import firefly_client
from worker.services.transaction_processor import process_new_emails

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_poll_task: asyncio.Task | None = None
_last_poll: datetime | None = None
_total_processed: int = 0


async def _poll_loop():
    global _last_poll, _total_processed
    while True:
        try:
            logger.info("Polling for new emails...")
            result = await process_new_emails()
            _last_poll = datetime.now()
            _total_processed += result.new_count

            for item in result.pending_review:
                if item["type"] == "category_confirmation":
                    await ask_category_confirmation(
                        transaction=item["transaction"],
                        suggested_category=item.get("suggested_category"),
                        parsed=item["parsed"],
                    )
                    if item.get("large_amount"):
                        await send_large_amount_confirmation(item["parsed"])
                elif item["type"] == "unknown_account":
                    await notify_unknown_account(item["parsed"])

            if result.new_count > 0:
                logger.info(
                    "Processed %d new transactions (%d auto, %d pending)",
                    result.new_count,
                    result.auto_categorized,
                    len(result.pending_review),
                )
        except Exception:
            logger.exception("Error in poll loop")

        await asyncio.sleep(POLL_INTERVAL_MINUTES * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poll_task

    # Start Telegram bot
    telegram_app = get_application()
    await telegram_app.initialize()
    await telegram_app.start()

    if TELEGRAM_WEBHOOK_URL:
        await telegram_app.bot.set_webhook(TELEGRAM_WEBHOOK_URL)
        logger.info("Telegram webhook set to %s", TELEGRAM_WEBHOOK_URL)
    else:
        await telegram_app.updater.start_polling()
        logger.info("Telegram polling started")

    # Start email polling background task
    _poll_task = asyncio.create_task(_poll_loop())
    logger.info("Email polling started (every %d minutes)", POLL_INTERVAL_MINUTES)

    await send_message("👋 Mdm Huat is here! Ready to track your money ah.")

    yield

    # Shutdown
    if _poll_task:
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass

    if TELEGRAM_WEBHOOK_URL:
        await telegram_app.bot.delete_webhook()
    else:
        await telegram_app.updater.stop()

    await telegram_app.stop()
    await telegram_app.shutdown()
    await firefly_client.close()
    logger.info("Worker shut down cleanly")


app = FastAPI(title="Finance Tracker Worker", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "last_poll": _last_poll.isoformat() if _last_poll else None,
        "total_processed": _total_processed,
    }


@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    telegram_app = get_application()
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
