import asyncio
import time

from app.config import get_settings
from app.llm.client import ChatClient, Provider
from app.llm.types import ChatMessage, ToolSpec

settings = get_settings()

CANDIDATES = [
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "z-ai/glm-5.3-flash",
    "moonshotai/kimi-k2.6",
    "mistralai/mistral-large-2-instruct",
    "openai/gpt-oss-20b",
    "nvidia/nemotron-nano-3-30b-a3b",
]

TOOL = ToolSpec(
    name="kb_search",
    description="Search the tenant knowledge base for platform compliance rules.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "search query"}},
        "required": ["query"],
    },
)


async def probe(model: str) -> None:
    client = ChatClient(
        [
            Provider(
                name="nvidia",
                base_url=settings.nvidia_base_url,
                api_key=settings.nvidia_api_key,
                default_model=model,
            )
        ]
    )
    started = time.perf_counter()
    try:
        result = await client.chat(
            [
                ChatMessage(
                    role="user",
                    content='查询知识库：Amazon 美国站儿童玩具标题能不能出现 "best seller"？',
                )
            ],
            tools=[TOOL],
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        calls = [(c.name, c.arguments) for c in result.tool_calls]
        print(f"{model}: OK {elapsed}ms tool_calls={calls} content={result.content[:60]!r}")
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.perf_counter() - started) * 1000)
        print(f"{model}: FAILED {elapsed}ms {type(exc).__name__}: {str(exc)[:220]}")


async def main() -> None:
    for model in CANDIDATES:
        await probe(model)


asyncio.run(main())
