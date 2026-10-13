import asyncio

import httpx

from app.config import get_settings

settings = get_settings()


async def main() -> None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(
            f"{settings.nvidia_base_url}/models",
            headers={"Authorization": f"Bearer {settings.nvidia_api_key}"},
        )
        print("status:", r.status_code)
        body = r.json()
        ids = sorted(m["id"] for m in body.get("data", []))
        print("total:", len(ids))
        for model_id in ids:
            print(" ", model_id)


asyncio.run(main())
