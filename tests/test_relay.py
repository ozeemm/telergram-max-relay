import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.config import AppConfig, load_config
from app.green_api import extract_incoming_text
from app.green_api import GreenApiClient
from app.main import process_notification, split_text
from app.state import StateStore


class IncomingMessageTests(unittest.TestCase):
    def test_extracts_text_from_incoming_message(self) -> None:
        body = {
            "typeWebhook": "incomingMessageReceived",
            "senderData": {"chatId": "max-contact"},
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {"textMessage": "hello"},
            },
        }

        self.assertEqual(
            extract_incoming_text(body),
            ("max-contact", "hello"),
        )

    def test_ignores_non_incoming_notifications(self) -> None:
        self.assertEqual(
            extract_incoming_text({"typeWebhook": "outgoingMessageReceived"}),
            (None, None),
        )

    def test_returns_chat_without_text_for_unsupported_message(self) -> None:
        body = {
            "typeWebhook": "incomingMessageReceived",
            "senderData": {"chatId": "max-contact"},
            "messageData": {"typeMessage": "imageMessage"},
        }

        self.assertEqual(extract_incoming_text(body), ("max-contact", None))


class TextSplittingTests(unittest.TestCase):
    def test_splits_long_text_without_losing_content(self) -> None:
        text = "a" * 8100

        parts = split_text(text)

        self.assertEqual([len(part) for part in parts], [4000, 4000, 100])
        self.assertEqual("".join(parts), text)

    def test_empty_text_has_no_parts(self) -> None:
        self.assertEqual(split_text(""), [])


class GreenApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_message_uses_green_api_v3_endpoint(self) -> None:
        requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"idMessage": "sent"}, request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        ) as http_client:
            client = GreenApiClient("instance-id", "api-token", http_client)
            await client.send_message("max-contact", "hello")

        self.assertEqual(
            requests[0].url.path,
            "/v3/waInstanceinstance-id/sendMessage/api-token",
        )
        self.assertEqual(
            requests[0].read(),
            b'{"chatId":"max-contact","message":"hello"}',
        )


class NotificationRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state = StateStore(Path(self.temp_dir.name) / "state.sqlite3")
        self.config = AppConfig(
            telegram_bot_token="unused",
            telegram_user_id=123,
            green_api_instance_id="unused",
            green_api_token="unused",
            max_chat_id="max-contact",
            state_path=Path(self.temp_dir.name) / "state.sqlite3",
        )

    async def asyncTearDown(self) -> None:
        self.state.close()
        self.temp_dir.cleanup()

    async def test_delivers_only_configured_chat_once(self) -> None:
        class FakeBot:
            def __init__(self) -> None:
                self.sent: list[tuple[int, str]] = []

            async def send_message(self, chat_id: int, text: str) -> None:
                self.sent.append((chat_id, text))

        bot = FakeBot()
        notification = {
            "receiptId": 42,
            "body": {
                "typeWebhook": "incomingMessageReceived",
                "senderData": {"chatId": "max-contact"},
                "messageData": {
                    "textMessageData": {"textMessage": "hello"},
                },
            },
        }

        await process_notification(notification, bot, self.config, self.state)
        await process_notification(notification, bot, self.config, self.state)

        self.assertEqual(bot.sent, [(123, "hello")])

    async def test_does_not_deliver_other_max_chats(self) -> None:
        class FakeBot:
            def __init__(self) -> None:
                self.sent: list[tuple[int, str]] = []

            async def send_message(self, chat_id: int, text: str) -> None:
                self.sent.append((chat_id, text))

        bot = FakeBot()
        notification = {
            "receiptId": 43,
            "body": {
                "typeWebhook": "incomingMessageReceived",
                "senderData": {"chatId": "another-chat"},
                "messageData": {
                    "textMessageData": {"textMessage": "not for relay"},
                },
            },
        }

        await process_notification(notification, bot, self.config, self.state)

        self.assertEqual(bot.sent, [])


class ConfigurationTests(unittest.TestCase):
    def test_loads_chat_ids_and_secrets_from_environment(self) -> None:
        environment = {
            "TELEGRAM_BOT_TOKEN": "telegram-secret",
            "TELEGRAM_USER_ID": "123",
            "GREEN_API_INSTANCE_ID": "green-instance",
            "GREEN_API_TOKEN": "green-secret",
            "MAX_CHAT_ID": "max-contact",
            "STATE_PATH": "/tmp/relay-state.sqlite3",
        }

        with patch.dict("os.environ", environment, clear=True):
            config = load_config()

        self.assertEqual(config.telegram_user_id, 123)
        self.assertEqual(config.max_chat_id, "max-contact")
        self.assertEqual(config.telegram_bot_token, "telegram-secret")
        self.assertEqual(config.green_api_instance_id, "green-instance")
        self.assertEqual(config.green_api_token, "green-secret")

    def test_rejects_non_numeric_telegram_user_id(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TELEGRAM_BOT_TOKEN": "telegram-secret",
                "TELEGRAM_USER_ID": "not-a-number",
                "GREEN_API_INSTANCE_ID": "green-instance",
                "GREEN_API_TOKEN": "green-secret",
                "MAX_CHAT_ID": "max-contact",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "TELEGRAM_USER_ID"):
                load_config()


if __name__ == "__main__":
    unittest.main()
