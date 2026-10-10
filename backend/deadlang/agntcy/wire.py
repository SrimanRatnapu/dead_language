"""A2A `message/send` envelopes as they travel over SLIM, shared by serve.py (server) and transport.py (client).

Bodies follow plan 01 §4.4: the request is one text part holding the JSON of a SpecialistCall or
DeliberationTurn (or a broadcast payload), and the reply is one text part holding the reply model's JSON.
The envelope is the same JSON-RPC the SDK's own A2A client sends, built with the SDK's message_translator.
"""
from __future__ import annotations

import json
from uuid import uuid4

from a2a.types import Message as A2AMessage
from a2a.types import MessageSendParams, Part, Role, SendMessageRequest, TextPart
from agntcy_app_sdk.semantic.a2a.client.utils import message_translator
from agntcy_app_sdk.semantic.message import Message

ORG_NAMESPACE = "default/default"


class WireError(Exception):
    """The reply was a JSON-RPC error or had no text in it."""


def slim_name(agent_name: str) -> str:
    """The SLIM identity (and topic) an agent is served under."""
    return f"{ORG_NAMESPACE}/{agent_name}"


def request_message(text: str) -> Message:
    rpc = SendMessageRequest(id=str(uuid4()), params=MessageSendParams(message=A2AMessage(
        role=Role.user, parts=[Part(root=TextPart(text=text))], message_id=str(uuid4()))))
    return message_translator(request=rpc.model_dump(mode="json", exclude_none=True))


def reply_text(message: Message) -> str:
    payload = message.payload
    data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    if "error" in data:
        err = data["error"]
        raise WireError((err.get("message") or json.dumps(err)) if isinstance(err, dict) else str(err))
    result = data.get("result") or {}
    parts = result.get("parts") or result.get("status", {}).get("message", {}).get("parts") or []
    for part in parts:
        if part.get("kind") == "text":
            return part["text"]
    raise WireError("the reply had no text part")
