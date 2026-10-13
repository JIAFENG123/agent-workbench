import asyncio
import json
import re
import time

from app.config import get_settings
from app.llm.client import ChatClient, Provider
from app.llm.types import ChatMessage

settings = get_settings()

QUERY = 'Amazon 美国站儿童玩具标题能不能出现 "best seller"？'
SYSTEM = """You rewrite a user's search query so a retrieval system finds more relevant
policy clauses. Produce 3 alternative phrasings that keep the original intent but vary the
wording, terminology and level of abstraction. Reply with a JSON array of strings and nothing
else."""
_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)

CANDIDATES = [
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "deepseek-ai/deepseek-v4-flash-0731",
    "z-ai/glm-5.3-flash",
    "meta/muse-glimmer-30b",
    "mistralai/mistral-nemotron",
    "nvidia/nemotron-3-super-120b-a12b",
]


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
            [ChatMessage(role="system", content=SYSTEM), ChatMessage(role="user", content=QUERY)],
            temperature=0.4,
            max_tokens=256,
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        match = _JSON_ARRAY.search(result.content)
        if not match:
            print(f"{model}: {elapsed}ms NO-JSON content={result.content[:120]!r}")
            return
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            print(f"{model}: {elapsed}ms BAD-JSON {exc} raw={match.group(0)[:120]!r}")
            return
        variants = [v for v in parsed if isinstance(v, str)]
        print(f"{model}: {elapsed}ms OK variants={len(variants)}")
        for variant in variants:
            print(f"    - {variant}")
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.perf_counter() - started) * 1000)
        print(f"{model}: {elapsed}ms FAILED {str(exc)[:180]}")


async def main() -> None:
    for model in CANDIDATES:
        await probe(model)


asyncio.run(main())
