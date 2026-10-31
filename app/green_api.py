from typing import Any

import httpx


class GreenApiError(RuntimeError):
    pass


class GreenApiClient:
    def __init__(
        self,
        instance_id: str,
        api_token: str,
        client: httpx.AsyncClient,
        base_url: str = "https://api.green-api.com/v3",
    ) -> None:
        self.instance_id = instance_id
        self.api_token = api_token
        self.client = client
        self.base_url = base_url.rstrip("/")

    def _url(self, method: str, receipt_id: str | int | None = None) -> str:
        url = (
            f"{self.base_url}/waInstance{self.instance_id}/"
            f"{method}/{self.api_token}"
        )
        if receipt_id is not None:
            url = f"{url}/{receipt_id}"
        return url

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._request(
            "POST",
            self._url("sendMessage"),
            json={"chatId": chat_id, "message": text},
        )

    async def receive_notification(self) -> dict[str, Any] | None:
        data = await self._request("GET", self._url("receiveNotification"))
        if data is None:
            return None
        if not isinstance(data, dict):
            raise GreenApiError("GREEN-API returned an invalid notification")
        return data

    async def delete_notification(self, receipt_id: str | int) -> None:
        await self._request(
            "DELETE",
            self._url("deleteNotification", receipt_id),
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = await self.client.request(method, url, **kwargs)
        except httpx.TimeoutException:
            raise GreenApiError("GREEN-API request timed out") from None
        except httpx.RequestError:
            raise GreenApiError("Could not connect to GREEN-API") from None

        if response.is_error:
            raise GreenApiError(
                f"GREEN-API returned HTTP {response.status_code}"
            )

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise GreenApiError("GREEN-API returned invalid JSON") from None


def extract_incoming_text(body: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (sender chat ID, text) for supported incoming text notifications."""
    if body.get("typeWebhook") != "incomingMessageReceived":
        return None, None

    sender_data = body.get("senderData")
    message_data = body.get("messageData")
    if not isinstance(sender_data, dict) or not isinstance(message_data, dict):
        return None, None

    sender_chat_id = sender_data.get("chatId")
    text_data = message_data.get("textMessageData")
    if not isinstance(sender_chat_id, str) or not isinstance(text_data, dict):
        return sender_chat_id if isinstance(sender_chat_id, str) else None, None

    text = text_data.get("textMessage")
    return sender_chat_id, text if isinstance(text, str) and text else None
