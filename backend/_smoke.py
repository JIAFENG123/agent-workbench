import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
EMAIL = f"smoke{int(time.time())}@example.com"
PASSWORD = "password123"

DOC = """# Amazon 美国站 儿童玩具 上架规则

## 标题规范
标题不得出现 "best seller"、"top rated"、"cheapest" 等带有排名或促销暗示的词汇。
标题中的品牌名必须与品牌备案一致，长度不得超过 200 个字符。

## 儿童玩具合规
面向 12 岁以下儿童的玩具必须提供 CPC 证书（Children's Product Certificate），
并符合 ASTM F963 与 CPSIA 铅含量限制要求。缺少 CPC 的商品会被强制下架。

## 关键词与描述
五点描述中禁止出现医疗功效声明，禁止出现竞品品牌名称。
"""


def main() -> int:
    with httpx.Client(timeout=120.0) as client:
        r = client.post(f"{BASE}/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
        print("register:", r.status_code)
        if r.status_code != 201:
            print(r.text)
            return 1
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = client.get(f"{BASE}/api/agents", headers=headers)
        print("agents:", r.status_code, [a["key"] for a in r.json()])

        r = client.post(
            f"{BASE}/api/kb/documents",
            headers=headers,
            files={"file": ("amazon-toy-rules.md", DOC.encode("utf-8"), "text/markdown")},
        )
        print("upload:", r.status_code)
        if r.status_code != 202:
            print(r.text)
            return 1
        doc_id = r.json()["id"]

        deadline = time.time() + 120
        status = None
        while time.time() < deadline:
            docs = client.get(f"{BASE}/api/kb/documents", headers=headers).json()
            doc = next(d for d in docs if d["id"] == doc_id)
            status = doc["status"]
            if status in ("ready", "failed"):
                print("index status:", status, "chunks:", doc["chunk_count"], "error:", doc["error"])
                break
            time.sleep(2)
        else:
            print("index timed out, last status:", status)
            return 1

        if status != "ready":
            return 1

        r = client.post(
            f"{BASE}/api/runs",
            headers=headers,
            json={
                "agent_key": "compliance",
                "input": 'Amazon 美国站卖儿童玩具，标题里能不能出现 "best seller" 这种词？',
            },
        )
        print("create run:", r.status_code)
        if r.status_code != 202:
            print(r.text)
            return 1
        run_id = r.json()["run_id"]

        deadline = time.time() + 240
        while time.time() < deadline:
            run = client.get(f"{BASE}/api/runs/{run_id}", headers=headers).json()
            if run["status"] in ("succeeded", "failed", "interrupted", "canceled"):
                print("run status:", run["status"])
                print("tokens:", run["prompt_tokens"], "+", run["completion_tokens"])
                print("latency_ms:", run["latency_ms"])
                if run.get("error"):
                    print("error:", run["error"])
                result = run.get("result") or {}
                print("--- answer ---")
                print(result.get("answer") or result)
                print("--- citations ---")
                for c in (result.get("citations") or []):
                    print(" ", c.get("index"), c.get("filename"), "score", c.get("score"))
                return 0 if run["status"] == "succeeded" else 1
            time.sleep(3)
        print("run timed out")
        return 1


if __name__ == "__main__":
    sys.exit(main())
