from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl


def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """Verify Telegram Mini App initData signature.

    Returns parsed user payload when the signature is valid.
    """

    if not init_data or not bot_token:
        return None

    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = values.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        user_raw = values.get("user")
        return json.loads(user_raw) if user_raw else None
    except Exception:
        return None
