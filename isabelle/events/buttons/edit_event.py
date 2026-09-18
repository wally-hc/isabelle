from typing import Any
from typing import Callable

from slack_sdk.web.async_client import AsyncWebClient

from isabelle.authz import can_edit_event
from isabelle.utils.env import env
from isabelle.views.edit_event import get_edit_event_modal


async def handle_edit_event_btn(ack: Callable, body: dict[str, Any], client: AsyncWebClient):
    await ack()
    user_id = body["user"]["id"]
    value = body["actions"][0]["value"]

    event = await env.database.get_event(value)
    if not event:
        await client.chat_postEphemeral(
            user=user_id,
            channel=user_id,
            text=f"Event with id `{value}` not found.",
        )
        return

    if not can_edit_event(user_id, event):
        await client.chat_postEphemeral(
            user=user_id,
            channel=user_id,
            text="You are not authorised to edit this event.",
        )
        return

    await client.views_open(view= await get_edit_event_modal(value), trigger_id=body["trigger_id"])
