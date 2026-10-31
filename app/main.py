import asyncio
import logging
import os
from typing import Any

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.config import AppConfig, load_config
from app.green_api import GreenApiClient, GreenApiError, extract_incoming_text
from app.state import StateStore

LOGGER = logging.getLogger("tg_max_proxy")
TELEGRAM_TEXT_LIMIT = 4000


def split_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def is_authorized(message: Message, config: AppConfig) -> bool:
    return (
        message.from_user is not None
        and message.from_user.id == config.telegram_user_id
        and message.chat.type == "private"
        and message.chat.id == config.telegram_user_id
    )


async def relay_to_max(
    message: Message, config: AppConfig, green_api: GreenApiClient
) -> None:
    if not is_authorized(message, config):
        return
    if not message.text:
        await message.answer("Пока поддерживаются только текстовые сообщения.")
        return

    try:
        await green_api.send_message(config.max_chat_id, message.text)
    except GreenApiError as exc:
        LOGGER.error("Failed to deliver Telegram message to MAX (%s)", type(exc).__name__)
        await message.answer("Не удалось отправить сообщение в MAX. Попробуйте позже.")


async def send_to_telegram(bot: Bot, chat_id: int, text: str) -> None:
    for part in split_text(text):
        await bot.send_message(chat_id=chat_id, text=part)


async def process_notification(
    notification: dict[str, Any],
    bot: Bot,
    config: AppConfig,
    state: StateStore,
) -> None:
    receipt_id = notification.get("receiptId")
    body = notification.get("body")
    if receipt_id is None or not isinstance(body, dict):
        raise GreenApiError("GREEN-API notification has an invalid shape")

    receipt_key = str(receipt_id)
    if state.is_processed(receipt_key):
        return

    sender_chat_id, text = extract_incoming_text(body)
    if sender_chat_id != config.max_chat_id:
        state.mark_processed(receipt_key)
        return
    if text is None:
        LOGGER.info("Ignoring unsupported or empty message from the configured MAX chat")
        state.mark_processed(receipt_key)
        return

    await send_to_telegram(bot, config.telegram_user_id, text)
    state.mark_processed(receipt_key)


async def poll_max(
    bot: Bot,
    config: AppConfig,
    green_api: GreenApiClient,
    state: StateStore,
) -> None:
    while True:
        try:
            notification = await green_api.receive_notification()
            if notification is None:
                await asyncio.sleep(0.25)
                continue

            await process_notification(notification, bot, config, state)
            await green_api.delete_notification(notification["receiptId"])
        except asyncio.CancelledError:
            raise
        except (GreenApiError, TelegramAPIError, KeyError, TypeError) as exc:
            LOGGER.error(
                "Failed to process a GREEN-API notification; it will be retried (%s)",
                type(exc).__name__,
            )
            await asyncio.sleep(2)


async def run(config: AppConfig) -> None:
    bot = Bot(token=config.telegram_bot_token)
    dispatcher = Dispatcher()
    http_timeout = httpx.Timeout(connect=10, read=190, write=10, pool=10)
    async with httpx.AsyncClient(timeout=http_timeout) as http_client:
        green_api = GreenApiClient(
            config.green_api_instance_id,
            config.green_api_token,
            http_client,
        )
        state = StateStore(config.state_path)

        async def start_handler(message: Message) -> None:
            if is_authorized(message, config):
                await message.answer(
                    "Бот готов. Текстовые сообщения пересылаются между Telegram и MAX."
                )

        async def text_handler(message: Message) -> None:
            await relay_to_max(message, config, green_api)

        async def other_message_handler(message: Message) -> None:
            await relay_to_max(message, config, green_api)

        dispatcher.message.register(start_handler, CommandStart())
        dispatcher.message.register(text_handler, F.text)
        dispatcher.message.register(other_message_handler)

        notification_task = asyncio.create_task(
            poll_max(bot, config, green_api, state),
            name="green-api-notifications",
        )
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            await dispatcher.start_polling(
                bot,
                allowed_updates=dispatcher.resolve_used_update_types(),
            )
        finally:
            notification_task.cancel()
            await asyncio.gather(notification_task, return_exceptions=True)
            state.close()
            await bot.session.close()


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = load_config()
    await run(config)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
