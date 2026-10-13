import asyncio
import json

import httpx

from app.config import get_settings

settings = get_settings()

MODEL = "nvidia/llama-nemotron-rerank-vl-1b-v2"
QUERY = 'Amazon 美国站儿童玩具标题能不能出现 "best seller"？'
PASSAGES = [
    "标题不得出现 best seller、top rated 等带有排名或促销暗示的词汇。",
    "面向 12 岁以下儿童的玩具必须提供 CPC 证书并符合 ASTM F963。",
    "五点描述中禁止出现医疗功效声明，禁止出现竞品品牌名称。",
]

ENDPOINTS = {
    "retrieval/reranking": f"https://ai.api.nvidia.com/v1/retrieval/{MODEL.replace('.', '_')}/reranking",
    "v1/ranking": "https://ai.api.nvidia.com/v1/ranking",
}

BODIES = {
    "passages-style": {
        "model": MODEL,
        "query": {"text": QUERY},
        "passages": [{"text": p} for p in PASSAGES],
        "truncate": "END",
    },
    "documents-style": {
        "model": MODEL,
        "query": QUERY,
        "documents": PASSAGES,
        "top_n": 3,
    },
}


async def main() -> None:
    headers = {
        "Authorization": f"Bearer {settings.nvidia_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        for endpoint_name, url in ENDPOINTS.items():
            for body_name, body in BODIES.items():
                try:
                    r = await client.post(url, json=body, headers=headers)
                    text = r.text[:400]
                    print(f"[{endpoint_name} + {body_name}] -> {r.status_code} {text}")
                    if r.status_code == 200:
                        print("   parsed:", json.dumps(r.json(), ensure_ascii=False)[:300])
                except Exception as exc:  # noqa: BLE001
                    print(f"[{endpoint_name} + {body_name}] -> ERROR {exc}")


asyncio.run(main())
