import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    telegram_bot_token: str
    telegram_user_id: int
    green_api_instance_id: str
    green_api_token: str
    max_chat_id: str
    state_path: Path


def load_config() -> AppConfig:
    try:
        telegram_user_id = int(os.getenv("TELEGRAM_USER_ID", "").strip())
    except ValueError as exc:
        raise RuntimeError("Set TELEGRAM_USER_ID to your numeric Telegram user ID") from exc

    if telegram_user_id <= 0:
        raise RuntimeError("TELEGRAM_USER_ID must be a positive number")

    max_chat_id = os.getenv("MAX_CHAT_ID", "").strip()
    if not max_chat_id or max_chat_id.startswith("REPLACE_"):
        raise RuntimeError("Set MAX_CHAT_ID to the target MAX chat ID")

    secrets = {
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        "green_api_instance_id": os.getenv("GREEN_API_INSTANCE_ID", "").strip(),
        "green_api_token": os.getenv("GREEN_API_TOKEN", "").strip(),
    }
    missing_secrets = [
        name
        for name, value in secrets.items()
        if not value
    ]
    if missing_secrets:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing_secrets)
        )

    return AppConfig(
        telegram_bot_token=secrets["telegram_bot_token"],
        telegram_user_id=telegram_user_id,
        green_api_instance_id=secrets["green_api_instance_id"],
        green_api_token=secrets["green_api_token"],
        max_chat_id=max_chat_id,
        state_path=Path(os.getenv("STATE_PATH", "/data/state.sqlite3")),
    )
