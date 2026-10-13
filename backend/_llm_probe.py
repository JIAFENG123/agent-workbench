import asyncio

from app.llm.client import get_chat_client
from app.llm.types import ChatMessage


async def main() -> None:
    client = get_chat_client()
    print("providers:", [(p.name, p.default_model, p.base_url) for p in client.providers])
    try:
        result = await client.chat([ChatMessage(role="user", content="say hi in one word")])
        print("ok:", repr(result.content), result.model, result.provider)
    except Exception as exc:  # noqa: BLE001
        print("FAILED:", type(exc).__name__, exc)


asyncio.run(main())
