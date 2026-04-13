import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

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
from worker.integrations import exchange_rate, firefly_client, ibkr_flex
from worker.services.transaction_processor import process_new_emails

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_poll_task: asyncio.Task | None = None
_ibkr_task: asyncio.Task | None = None
_salary_task: asyncio.Task | None = None
_last_poll: datetime | None = None
_total_processed: int = 0

IBKR_UPDATE_HOUR = 7  # 7am SGT
SALARY_CHECK_HOUR = 8  # 8am SGT


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
                        foreign_info=item.get("foreign_info"),
                    )
                    if item.get("large_amount"):
                        await send_large_amount_confirmation(
                            item["parsed"], foreign_info=item.get("foreign_info")
                        )
                elif item["type"] == "unknown_account":
                    await notify_unknown_account(item["parsed"])

            if result.new_count > 0:
                logger.info(
                    "Processed %d new transactions (%d pending)",
                    result.new_count,
                    len(result.pending_review),
                )
        except Exception:
            logger.exception("Error in poll loop")

        await asyncio.sleep(POLL_INTERVAL_MINUTES * 60)


def _seconds_until_next(hour: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _ibkr_daily_loop():
    while True:
        wait = _seconds_until_next(IBKR_UPDATE_HOUR)
        logger.info("Next IBKR update in %.0f hours", wait / 3600)
        await asyncio.sleep(wait)

        try:
            ibkr_data = await ibkr_flex.fetch_ibkr_data()
            if ibkr_data and ibkr_data["total_equity"] > 0:
                from worker.bot.commands import _update_account_balance

                updated = await _update_account_balance("IBKR", ibkr_data["total_equity"])
                if updated:
                    logger.info("IBKR daily update: %s", updated)
        except ibkr_flex.IBKRTokenError as e:
            await send_message(f"⚠️ IBKR token expired: {e}\nPlease renew at IBKR Client Portal.")
        except Exception:
            logger.exception("Error in IBKR daily loop")


async def _salary_daily_loop():
    while True:
        wait = _seconds_until_next(SALARY_CHECK_HOUR)
        logger.info("Next salary check in %.0f hours", wait / 3600)
        await asyncio.sleep(wait)

        try:
            from worker.services.salary import run_salary_check

            results = await run_salary_check()
            for result in results:
                await send_message(
                    f"💼 Salary deposited\n──────────\n{result}",
                    parse_mode="HTML",
                )
                logger.info("Salary deposited: %s", result)
        except Exception:
            logger.exception("Error in salary daily loop")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poll_task, _ibkr_task, _salary_task

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

    # Start background tasks
    _poll_task = asyncio.create_task(_poll_loop())
    _ibkr_task = asyncio.create_task(_ibkr_daily_loop())
    _salary_task = asyncio.create_task(_salary_daily_loop())
    logger.info("Email polling started (every %d minutes)", POLL_INTERVAL_MINUTES)
    logger.info("IBKR daily update started")
    logger.info("Salary check started")

    await send_message("👋 Mdm Huat is here! Ready to track your money.")

    yield

    # Shutdown
    for task in (_poll_task, _ibkr_task, _salary_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    if TELEGRAM_WEBHOOK_URL:
        await telegram_app.bot.delete_webhook()
    else:
        await telegram_app.updater.stop()

    await telegram_app.stop()
    await telegram_app.shutdown()
    await exchange_rate.close()
    await firefly_client.close()
    logger.info("Worker shut down cleanly")


app = FastAPI(title="Finance Tracker Worker", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    from worker.bot.telegram_bot import get_last_telegram_activity

    now = datetime.now()
    last_tg = get_last_telegram_activity()

    # Email polling should happen every POLL_INTERVAL_MINUTES
    # Allow 2x the interval as grace period; None means just started
    email_healthy = (
        _last_poll is None or (now - _last_poll).total_seconds() < POLL_INTERVAL_MINUTES * 60 * 2
    )

    # If we've never received a Telegram update, that's fine (no one has messaged yet)
    # But if we did receive one before and it's been >30 min, polling might be dead
    tg_healthy = last_tg is None or (now - last_tg).total_seconds() < 1800

    status = "ok" if (email_healthy and tg_healthy) else "degraded"

    return {
        "status": status,
        "last_poll": _last_poll.isoformat() if _last_poll else None,
        "last_telegram": last_tg.isoformat() if last_tg else None,
        "total_processed": _total_processed,
    }


@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    try:
        telegram_app = get_application()
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
    except Exception:
        logger.exception("Failed to process Telegram webhook")
    return {"ok": True}
