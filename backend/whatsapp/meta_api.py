import logging
import asyncio
from typing import List, Optional
import httpx
from config.settings import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
)
from whatsapp.formatter import format_for_whatsapp, split_message

log = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class MetaWhatsAppClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
    ):
        self.access_token = access_token or WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = phone_number_id or WHATSAPP_PHONE_NUMBER_ID
        self.endpoint = f"{BASE_URL}/{self.phone_number_id}/messages"

    def is_configured(self) -> bool:
        return bool(self.access_token and self.phone_number_id)

    async def mark_as_read(self, message_id: str) -> bool:
        """Mark an incoming message as read (blue ticks)."""
        if not self.is_configured():
            log.warning("[meta_api] WhatsApp client not fully configured; skipping mark_as_read.")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.endpoint, headers=headers, json=payload)
                return resp.status_code == 200
        except Exception as e:
            log.error(f"[meta_api] Failed to mark message {message_id} as read: {e}")
            return False

    async def send_text_message(
        self,
        to_phone: str,
        message: str,
        format_markdown: bool = True,
    ) -> List[dict]:
        """
        Sends one or more text messages to a phone number.
        Automatically splits long text into WhatsApp-compliant parts.
        """
        if not self.is_configured():
            log.warning(
                f"[meta_api] WhatsApp credentials missing. Message to {to_phone} not sent.\nContent preview: {message[:120]}..."
            )
            return [{"status": "simulated", "recipient": to_phone}]

        if format_markdown:
            message = format_for_whatsapp(message)

        parts = split_message(message, max_length=3800)
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        results = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            for part in parts:
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to_phone,
                    "type": "text",
                    "text": {
                        "preview_url": False,
                        "body": part,
                    },
                }

                try:
                    resp = await client.post(self.endpoint, headers=headers, json=payload)
                    data = resp.json()
                    if resp.status_code in (200, 201):
                        results.append({"status": "delivered", "data": data})
                    else:
                        log.error(f"[meta_api] WhatsApp API error ({resp.status_code}): {resp.text}")
                        results.append({"status": "error", "error": data})
                except Exception as e:
                    log.error(f"[meta_api] Request failed: {e}")
                    results.append({"status": "failed", "error": str(e)})

                # Brief delay between sequential multi-part messages
                if len(parts) > 1:
                    await asyncio.sleep(0.5)

        return results
