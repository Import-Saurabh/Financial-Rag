import logging
import asyncio
from typing import Optional
from fastapi import APIRouter, Request, Query, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

from config.settings import WHATSAPP_VERIFY_TOKEN
from whatsapp.meta_api import MetaWhatsAppClient
from whatsapp.guardrails import (
    auth_guard,
    rate_limit_check,
    sanitize_input,
    filter_output,
    enforce_grounding,
    add_disclaimer_if_needed,
    quality_gate,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/whatsapp", tags=["whatsapp"])
whatsapp_client = MetaWhatsAppClient()


@router.get("")
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """
    Verification challenge endpoint for Meta WhatsApp Cloud API.
    Configured in the Meta App Dashboard under WhatsApp > Configuration > Callback URL.
    """
    token = WHATSAPP_VERIFY_TOKEN or "finrag_verify_token_2026"

    if hub_mode == "subscribe" and hub_verify_token == token:
        log.info("[whatsapp-webhook] Webhook successfully verified with Meta.")
        return PlainTextResponse(content=hub_challenge or "", status_code=200)

    log.warning("[whatsapp-webhook] Webhook verification failed. Tokens did not match.")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


async def process_whatsapp_message(from_number: str, message_id: str, message_body: str):
    """
    Background worker that executes RAG pipeline with full guardrail protections.
    """
    t0 = asyncio.get_event_loop().time()

    # 1. Auth Guard (Whitelist verification)
    if not auth_guard(from_number):
        log.warning(f"[whatsapp] Blocked message from unauthorized number: {from_number}")
        return

    # 2. Mark incoming message as read immediately
    if message_id:
        asyncio.create_task(whatsapp_client.mark_as_read(message_id))

    # 3. Rate Limit Check
    allowed, rate_error = rate_limit_check(from_number)
    if not allowed:
        await whatsapp_client.send_text_message(from_number, rate_error or "Rate limit exceeded.")
        return

    # 4. Input Sanitization & Injection Check
    cleaned_query, is_suspicious = sanitize_input(message_body)
    if not cleaned_query:
        return

    log.info(f"[whatsapp] Received query from {from_number}: {cleaned_query!r} (suspicious={is_suspicious})")

    # 5. Quick help / greeting handler
    lower_query = cleaned_query.lower().strip()
    if lower_query in ("hi", "hello", "hey", "help", "/start", "menu"):
        help_text = (
            "👋 *Welcome to your Personal Financial Research Assistant!*\n\n"
            "You can ask me questions about Indian equities, concalls, and quarterly results, such as:\n"
            "• _What happened in Apollo Microsystems' latest concall?_\n"
            "• _Explain HAL's latest quarterly results._\n"
            "• _What guidance did management give for the coming financial year?_\n"
            "• _Compare the latest concall with the previous one._\n"
            "• _What are the major risks mentioned?_\n\n"
            "Simply send your question here."
        )
        await whatsapp_client.send_text_message(from_number, help_text)
        return

    # 6. Execute RAG Query via Financial RAG Server Core
    try:
        from server import _run_query, QueryRequest

        req = QueryRequest(
            query=cleaned_query,
            symbol=None,
            doc_type="both",
            provider="auto",
        )

        rag_result = await _run_query(req)
        raw_answer = rag_result.get("answer", "")
        sources = rag_result.get("sources", [])

    except Exception as exc:
        log.error(f"[whatsapp] Error running RAG pipeline: {exc}", exc_info=True)
        raw_answer = "⚠️ An error occurred while retrieving company documents. Please try again or rephrase your query."
        sources = []

    # 7. Apply Output Guardrails
    answer = filter_output(raw_answer)
    answer = enforce_grounding(answer, sources)
    answer = add_disclaimer_if_needed(answer)
    final_answer = quality_gate(answer)

    # 8. Send Formatted WhatsApp Response
    elapsed = round(asyncio.get_event_loop().time() - t0, 2)
    log.info(f"[whatsapp] Dispatching reply to {from_number} ({len(final_answer)} chars, {elapsed}s)")
    await whatsapp_client.send_text_message(from_number, final_answer)


@router.post("")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming webhook payloads from Meta WhatsApp Cloud API.
    Responds with HTTP 200 immediately and dispatches processing to background worker.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"status": "invalid json"})

    # Check that this is a WhatsApp API notification
    entry_list = data.get("entry", [])
    for entry in entry_list:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                # We currently process incoming text messages
                msg_type = msg.get("type")
                from_number = msg.get("from")
                msg_id = msg.get("id")

                if msg_type == "text" and from_number:
                    text_body = msg.get("text", {}).get("body", "")
                    background_tasks.add_task(
                        process_whatsapp_message,
                        from_number=from_number,
                        message_id=msg_id,
                        message_body=text_body,
                    )

    return JSONResponse(status_code=200, content={"status": "received"})
