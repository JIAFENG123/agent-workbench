# Agent Workbench

一个**可观测、可评测、可续跑的 Agent 运行时**，外加跑在它上面的第一个应用：**出海商品合规与上架助手**。

不依赖任何本地模型，全部跑在免费额度上：后端一个 Render 免费 Web Service，数据库用 Neon 免费版，模型走 NVIDIA NIM。

---

## 现在能做什么

- 注册即获得独立租户，知识库、运行记录、用量全部按租户隔离
- 上传平台规则文档（`.txt` / `.md` / `.pdf` / `.docx` / `.csv` / `.json`；文本自动识别 UTF-8 与 GB18030，PDF / DOCX 自动抽取正文）
- 走完整的检索链路：语义分块 → 嵌入 → 向量 + BM25 混合检索 → RRF 融合 → 交叉编码器重排 → 带引用来源返回
- 和 Agent 对话，流式看到「思考 → 调工具 → 再思考 → 给答案」的全过程
- 右侧实时画出执行轨迹、工具调用参数与耗时、引用来源
- **全链路可观测追踪（Tracing）**：分层捕获 ReAct 循环、LLM、工具执行与 RAG 各阶段 Span 树状图，提供 `/api/runs/{run_id}/trace` 接口
- **多轮会话记忆（Conversation Memory）**：按 `thread_id` 维护多轮对话滑动窗口与上下文落库持久化，支持历史重放
- **自动化评测与基准集（Eval Suite & Benchmark）**：包含 12 组出海黄金评测用例，量化 HitRate@5、MRR、Tool Accuracy、Faithfulness（忠实度）与违禁宣称校验，一键运行 `uv run python -m app.eval.cli`
- **多 Agent 支持**：内置「出海合规助手 (`compliance`)」与「出海 Listing 优化与 SEO 助手 (`listing_optimizer`)」
- 历史运行可回看，失败/中断状态如实标记

## 现在还不能做什么（P1–P3 待做）

诚实列一下，免得你按图索骥找不到：

- **断点续跑**：进程重启后任务会被标记为 `interrupted`，但不会从中间恢复（需要 LangGraph checkpointer）
- **人工审批（HITL）**：高风险项自动挂起等人确认，还没做
- **MCP 双向协议**：还没接
- **语义缓存 / 模型路由**：只有 `router.py` 的骨架，没有真正生效

---

## 没有服务器？本来就不需要服务器

这套东西**全程跑在免费平台上，不需要买任何服务器，也不需要绑信用卡**：

| 角色 | 用谁 | 免费额度 | 会不会休眠 |
|---|---|---|---|
| 后端 API | Render **Free Web Service**（Docker） | 512 MB / 0.1 CPU，750 实例小时每月 | 会，闲置 15 分钟 |
| 前端 | Render **Static Site** | 不限量，**不占实例小时** | 不会 |
| 数据库 | **Neon** Free | 0.5 GB + pgvector | 会，闲置 5 分钟 |
| 模型（对话/嵌入/重排） | **NVIDIA NIM** | 免费试用额度 | — |
| 定时任务 | **GitHub Actions** | 公有仓库免费且不限量 | — |

**而且你可以完全跳过本地环境，直接部署上线。** 本地那一套只是为了改代码时方便，不是必须的。

要做的事只有两件：先按下面「**第 1 步 拿 NVIDIA Key**」和「**第 2 步 建数据库**」拿到两样东西，然后直接跳到「**部署到 Render**」。

> **一个必须提前知道的风险。** Render 免费层明确写了：*服务发起大量对外流量时可能被暂停*，举的例子正好是「访问外部数据库」和「调用外部 API」——而本项目每次对话都要连 Neon、调 NVIDIA NIM，两条全中。
>
> 正常个人使用量不会有问题，但如果被暂停，只能升级到任意付费套餐才能恢复。心里有个数就行。

---

## 照着做：本地跑起来

### 第 0 步 · 准备

需要 Python 3.12、Node 20+、以及 [uv](https://docs.astral.sh/uv/)。

```bash
python --version    # 需要 3.12.x
node --version      # 需要 20 或更高
uv --version        # 没有就装：https://docs.astral.sh/uv/getting-started/installation/
```

### 第 1 步 · 拿 NVIDIA API Key

1. 打开 https://build.nvidia.com ，右上角登录（邮箱注册即可，免费）
2. 随便点开一个模型，页面右上角点 **Get API Key**
3. 复制 `nvapi-` 开头的那串

这一把 Key 同时用于对话模型、嵌入模型和重排模型，不用申请第二把。

### 第 2 步 · 建数据库（Neon 免费版）

> 为什么不用 Render 自带的免费 Postgres：**它 30 天就过期**。Neon 免费版是 0.5 GB 存储 + pgvector，不会到期。

1. 打开 https://neon.com 注册，新建一个 project（区域选新加坡，离国内近）
2. 在 Dashboard 找到 **Connection string**，形如：

   ```
   postgresql://neondb_owner:xxxx@ep-cool-name-123456.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```

3. 改造成 SQLAlchemy + asyncpg 能用的形式，做两处改动：

   - 协议头 `postgresql://` → `postgresql+asyncpg://`
   - 参数 `sslmode=require` → `ssl=require`（asyncpg 不认 libpq 的写法）

   最终长这样：

   ```
   postgresql+asyncpg://neondb_owner:xxxx@ep-cool-name-123456.ap-southeast-1.aws.neon.tech/neondb?ssl=require
   ```

> vector 扩展不用你手动建，第 3 步的迁移会自动执行 `CREATE EXTENSION IF NOT EXISTS vector`。

### 第 3 步 · 起后端

```bash
cd backend
uv sync --extra dev
```

复制配置模板，然后把上面两样填进去：

```bash
copy .env.example .env      # macOS / Linux: cp .env.example .env
```

打开 `.env`，只改这两行（其它保持默认即可）：

```ini
DATABASE_URL=postgresql+asyncpg://neondb_owner:xxxx@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?ssl=require
NVIDIA_API_KEY=nvapi-xxxxxxxxxxxx
```

建表：

```bash
uv run alembic upgrade head
```

起服务：

```bash
uv run uvicorn app.main:app --reload
```

看到 `Uvicorn running on http://127.0.0.1:8000` 就好了。另开一个终端确认一下：

```bash
curl http://127.0.0.1:8000/healthz
```

期望看到 `"status":"ok"`、`"database":true`、`"llm_configured":true`。任何一项不对，见文末排错表。

### 第 4 步 · 起前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:3000 。

> 想指向别的后端地址：`NUXT_PUBLIC_API_BASE=http://127.0.0.1:8000 npm run dev`

### 第 5 步 · 用起来

1. 注册一个账号（密码至少 8 位）
2. 左边点「**知识库**」→ 上传一份平台规则文档（`.txt` / `.md` / `.pdf` / `.docx` 都行）
   - 状态从「索引中」变成「已索引」就代表入库完成，看得到 chunk 数量
3. 回到「**对话**」，问一个必须查资料才能答的问题，例如：

   > Amazon 美国站卖儿童玩具，标题里能不能出现 "best seller" 这种词？

4. 你会看到：右侧轨迹里 `kb_search` 被调用 → 答案流式冒出来 → 引用来源列出编号和文件名

**到这儿就完事了。** 剩下的都是锦上添花。

---

## 部署到 Render

### 第 1 步 · 推到 GitHub

```bash
cd agent-workbench
git init && git add -A && git commit -m "feat: agent workbench"
git remote add origin git@github.com:<你的用户名>/agent-workbench.git
git push -u origin main
```

`.env` 已经在 `.gitignore` 里，不会被推上去。

### 第 2 步 · 建 Blueprint

1. 打开 https://dashboard.render.com ，点 **New → Blueprint**
2. 选中这个仓库，Render 会读根目录的 `render.yaml`
3. 它会创建两个服务：`agent-workbench-api`（Docker，免费套餐）和 `agent-workbench-web`（静态站）

`render.yaml` 里已经把后端区域设成了 **`singapore`**，离国内近很多。区域创建后不能改，如果 Blueprint 同步时报区域不可用，把 `region: singapore` 那一行删掉即可（会退回默认的 oregon，功能一样，就是慢一些）。

### 第 3 步 · 填环境变量

在 `agent-workbench-api` 的 **Environment** 里填三个（`JWT_SECRET` 是 Render 自动生成的，不用管）：

| Key | 值 |
|---|---|
| `DATABASE_URL` | 第 2 步那条 Neon 连接串 |
| `NVIDIA_API_KEY` | 你的 `nvapi-` Key |
| `CORS_ORIGINS` | 静态站的完整地址，例如 `https://agent-workbench-web.onrender.com` |

在 `agent-workbench-web` 里填一个：

| Key | 值 |
|---|---|
| `NUXT_PUBLIC_API_BASE` | 后端的完整地址，例如 `https://agent-workbench-api.onrender.com` |

> 这两个地址要**互相填对方**，而且要填 `https://` 开头的完整域名。填错的话前端会跨域报错。

### 第 4 步 · 触发重新部署

改完环境变量后，两个服务都点一次 **Manual Deploy → Deploy latest commit**。静态站必须重新构建，因为 `NUXT_PUBLIC_API_BASE` 是**构建时**写进产物里的。

### 第 5 步 · 打开防休眠

免费实例 15 分钟没请求就会休眠，下次访问要等 30–60 秒冷启。仓库里已经带了 `.github/workflows/keepalive.yml`：

1. 到 GitHub 仓库 → **Settings → Secrets and variables → Actions → Variables**
2. 新建一个变量 `API_BASE_URL`，值是你的后端地址（不带末尾斜杠）
3. Actions 里手动跑一次 `keepalive` 确认能通

> **两个必须知道的代价**：① 常驻一个服务每月约消耗 720 小时，而免费额度是 750 小时——所以**整个项目只能有一个常驻后端**，这也是前端必须做成静态站的原因；② GitHub 会在仓库 60 天无活动后停掉定时任务。这是 hobby 级取巧，生产环境应该上付费实例或者别省这个钱。

---

## 做完了怎么验收

逐条过一遍，全绿才算真的跑通了：

| 验收项 | 怎么验 | 通过标准 |
|---|---|---|
| 健康检查 | `curl <后端地址>/healthz` | `"status":"ok"`，`database` 和 `llm_configured` 都是 `true` |
| 知识库入库 | 上传一份 md，看文档列表 | 状态变「已索引」，chunk 数量 > 0 |
| 检索 + 引用 | 问一个必须查资料的问题 | 答案里出现 `[1]` `[2]`，右侧列出对应文件名 |
| 流式 | 观察回答过程 | 文字逐字出现，不是等几秒一次性蹦出来 |
| 工具调用可视化 | 看右侧轨迹 | `kb_search` 卡片可展开，看得到参数和耗时 |
| 会话隔离 | 注册第二个账号 | 看不到第一个账号的知识库和运行记录 |
| 鉴权 | `curl <后端地址>/api/runs` 不带 token | 返回 401 |
| 崩溃对账 | 运行时重启后端进程 | 那条运行记录变成 `interrupted`，不会永远卡在「运行中」 |
| 冷启动体验 | 静置 20 分钟后再访问 | 顶部出现「正在唤醒服务」，重试后成功 |
| 内存 | Render 面板看稳定态 | 稳定在 512 MB 以内，没有 OOM 重启 |

---

## 为什么这么设计

这六个决策都不是随手选的，都是被约束逼出来的。面试时这几条就是可讲的点：

| 决策 | 原因 |
|---|---|
| **不用 ChromaDB，改用 pgvector** | `chromadb` 的默认嵌入函数会拖进 `onnxruntime`，光依赖就 300 MB+，512 MB 的实例必爆。pgvector 走 psycopg，依赖极轻 |
| **不用 Celery / Redis worker** | Render 免费层**没有 background worker，也没有 cron**。长任务只能跑在 Web 进程内：`asyncio` + 任务表 + 启动时对账 |
| **不用 WebSocket，用 SSE** | 流式是纯下行。SSE 更简单、天然支持自动重连。人工审批是离散上行，走普通 REST 就够，不需要全双工 |
| **嵌入和重排都走 API，本地零模型** | 同上，内存装不下 `torch` / `sentence-transformers`。而且 NVIDIA NIM 这两个都是免费的 |
| **用 GitHub Actions 当定时器** | Render 免费层不给 cron。GH Actions 的 `schedule` 对公有仓库免费且不限量 |
| **前端是纯静态站，不是 SSR** | ① 静态站不计入 750 实例小时，也不休眠；② 这是个需要登录的仪表盘，服务端渲染只能渲染出一个未登录的空壳，没有收益 |
| **PDF / DOCX 用 pypdf + python-docx，且延迟导入** | 两者都是小依赖（最大的 lxml 约 4 MB），跟被否掉的 `onnxruntime`（300 MB+）不是一个量级；延迟导入让只传文本格式的进程不为它们付启动开销 |

还有两个容易被忽略但很关键的细节：

- **原生 `EventSource` 用不了**，因为它没法带 `Authorization` 头，而把 JWT 塞进 query string 会泄漏到访问日志里。所以前端是 `fetch` + `ReadableStream` 手动解析 SSE 帧的，顺带也就支持了 `Last-Event-ID` 断线重放。
- **`normalize()` 必须保留段落边界**。分块是靠空行切段落的；如果这里把连续空行合并掉，整篇文档会变成一个巨型块，段落感知的分块策略就全都失效了。这个坑是写测试时发现的。

更细的架构说明（模块划分、数据流、错误处理策略）在 [`docs/architecture.md`](docs/architecture.md)。

---

## 排错

| 现象 | 原因 / 处理 |
|---|---|
| `/healthz` 返回 `"database":false` | `DATABASE_URL` 不对。三个常见错误：忘了把 `postgresql://` 改成 `postgresql+asyncpg://`；`sslmode=require` 没改成 `ssl=require`；Neon 项目在休眠，第一次连接慢是正常的 |
| `alembic upgrade head` 报 `CREATE EXTENSION` 权限不足 | 你连的不是 owner 账号，或者该数据库不允许创建扩展。Neon 上默认 owner 可以创建 |
| `/healthz` 返回 `"llm_configured":false` | `NVIDIA_API_KEY` 没填，或者填的不是 `nvapi-` 开头的（NGC 的 Key 不一样） |
| 提问返回「知识库中没有检索到相关内容」 | 文档还在索引中，或者问的和文档内容真的不相关。先确认文档状态是「已索引」 |
| 前端报跨域错误 | `CORS_ORIGINS` 必须和后端实际被访问的地址**完全一致**（含 `https://`，不含末尾斜杠） |
| 前端能打开但所有请求都失败 | `NUXT_PUBLIC_API_BASE` 是构建时变量，改完必须重新构建静态站 |
| 上传中文文档乱码 | 正常情况下会自动按 UTF-8 → GB18030 顺序尝试解码。如果还是乱码，先转成 UTF-8 再传 |
| 上传 PDF 提示 no text layer | 那是扫描件，里面没有文字层。本项目不做 OCR（依赖太重），先用 OCR 工具转成文本再传 |
| 上传 .doc / .xls / .ppt 被拒 | 老版 Office 二进制格式还没接。另存为 `.docx`、`.pdf` 或纯文本再传 |
| 上传提示 chunk 超过上限 | 单个文档切出的片段太多（默认 10000 个），说明文件太大或段落过密。拆成几个文件分别上传，或调大 `MAX_CHUNKS_PER_DOCUMENT` |
| `npm install` 后 `tailwindcss` 不见了 | 环境里设了 `NODE_ENV=production`，npm 会因此**静默跳过所有 devDependencies**。前端目录里已经放了 `.npmrc` 写死 `include=dev` 来兜住这个坑 |
| 冷启动要等 30–60 秒 | 免费层 15 分钟无请求就休眠。跑一下 `.github/workflows/keepalive.yml`，或者接受它 |
| 服务被 Render 暂停了 | 免费层会暂停发起大量对外流量的服务（我们每次对话都要连 Neon + 调 NVIDIA NIM，正好命中）。只能升级到任意付费套餐恢复 |
| 运行记录卡在「运行中」 | 说明进程当时被重启了。启动时的对账逻辑会把它标成 `interrupted`，重新部署一次即可 |

---

## 目录结构

```
agent-workbench/
├─ backend/
│  ├─ app/
│  │  ├─ api/        路由：auth / kb / runs / meta
│  │  ├─ runtime/    Agent 内核：事件总线、ReAct 循环、任务管理器
│  │  ├─ rag/        分块、入库、混合检索、RRF、查询改写、检索编排
│  │  ├─ llm/        对话/嵌入/重排客户端、成本核算、模型路由
│  │  ├─ tools/      工具注册表 + 内置工具
│  │  ├─ agents/     Agent 定义
│  │  ├─ db/         模型与会话
│  │  └─ obs/        结构化日志、指标
│  ├─ migrations/    Alembic 迁移
│  ├─ tests/         67 个测试
│  └─ Dockerfile · docker-entrypoint.sh
├─ frontend/         Nuxt3 + TypeScript + Tailwind v4
├─ .github/workflows/  ci.yml · keepalive.yml
├─ docs/architecture.md
└─ render.yaml
```

---

## 开发命令

```bash
# 后端
cd backend
uv run pytest -q                        # 测试
uv run ruff check app tests             # 静态检查
uv run ruff format app tests            # 格式化
uv run mypy app                         # 类型检查
uv run alembic upgrade head             # 应用迁移
uv run alembic upgrade head --sql       # 只渲染 SQL，不连库（调试用）

# 前端
cd frontend
npm run dev                             # 开发服务器
npm run typecheck                       # 类型检查
npm run generate                        # 产出静态站到 .output/public
```
