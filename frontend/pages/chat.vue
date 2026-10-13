<script setup lang="ts">
import type { Agent, KbDocument, RunCreated, RunRecord } from '~/types/api'
import type { TimelineStep, ToolCallRecord } from '~/composables/useRunStream'

const api = useApi()
const { isAuthenticated, restore } = useAuth()
const stream = useRunStream()

const agents = ref<Agent[]>([])
const documents = ref<KbDocument[]>([])
const agentKey = ref('compliance')
const prompt = ref('')
const busy = ref(false)
const loading = ref(true)
const loadError = ref<string | null>(null)
const submitError = ref<string | null>(null)
const currentRunId = ref<string | null>(null)
const history = ref<RunRecord[]>([])
const historyRefreshing = ref(false)
const openingRunId = ref<string | null>(null)
const viewingHistory = ref(false)

const activeAgent = computed(() => agents.value.find((item) => item.key === agentKey.value) ?? null)
const readyDocuments = computed(() => documents.value.filter((item) => item.status === 'ready'))
const isStreaming = computed(
  () => stream.status.value === 'streaming' || stream.status.value === 'connecting',
)

/** Only show the answer panel once there is something to say — not as an empty box. */
const showAnswer = computed(() => !loading.value && stream.status.value !== 'idle')

const answerPhase = computed(() => {
  if (viewingHistory.value) return '历史运行'
  switch (stream.status.value) {
    case 'connecting':
      return '正在连接…'
    case 'streaming':
      return stream.answer.value ? '正在生成' : '思考中…'
    case 'done':
      return '已完成'
    case 'failed':
      return '已中止'
    default:
      return ''
  }
})

const STATUS_DOT: Record<string, string> = {
  succeeded: 'bg-emerald-500',
  failed: 'bg-rose-500',
  running: 'bg-amber-400',
  queued: 'bg-amber-400',
  canceled: 'bg-ink-500',
  interrupted: 'bg-ink-500',
}

const STATUS_LABEL: Record<string, string> = {
  succeeded: '已完成',
  failed: '失败',
  running: '运行中',
  queued: '排队中',
  canceled: '已取消',
  interrupted: '已中断',
}

/** Compact enough for a 220px rail: date + minutes, no seconds. */
function shortTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

async function bootstrap() {
  restore()
  if (!isAuthenticated.value) {
    await navigateTo('/')
    return
  }
  loading.value = true
  loadError.value = null
  try {
    const [agentList, documentList, runList] = await Promise.all([
      api.get<Agent[]>('/api/agents'),
      api.get<KbDocument[]>('/api/kb/documents'),
      api.get<RunRecord[]>('/api/runs?limit=20'),
    ])
    agents.value = agentList
    documents.value = documentList
    history.value = runList
    if (agentList.length && !agentList.some((item) => item.key === agentKey.value)) {
      agentKey.value = agentList[0]!.key
    }
  } catch (error) {
    loadError.value = (error as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(bootstrap)

async function refreshHistory() {
  historyRefreshing.value = true
  try {
    history.value = await api.get<RunRecord[]>('/api/runs?limit=20')
  } catch {
    // A stale sidebar is better than an error banner over a run that just succeeded.
  } finally {
    historyRefreshing.value = false
  }
}

async function submit() {
  const text = prompt.value.trim()
  if (!text || busy.value || isStreaming.value) return

  submitError.value = null
  busy.value = true
  viewingHistory.value = false

  try {
    const created = await api.post<RunCreated>('/api/runs', {
      agent_key: agentKey.value,
      input: text,
    })
    currentRunId.value = created.run_id
    prompt.value = ''
    void stream.start(created.run_id).then(refreshHistory)
  } catch (error) {
    submitError.value = (error as Error).message
  } finally {
    busy.value = false
  }
}

function onKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    event.preventDefault()
    void submit()
  }
}

async function openHistoricalRun(run: RunRecord) {
  if (isStreaming.value || openingRunId.value) return
  openingRunId.value = run.id
  submitError.value = null

  try {
    const detail = await api.get<RunRecord>(`/api/runs/${run.id}`)
    if (!detail.result) {
      submitError.value = '该运行没有产出结果（可能已失败或被中断）。'
      return
    }

    stream.stop()
    stream.reset()
    viewingHistory.value = true
    currentRunId.value = detail.id
    stream.answer.value = detail.result.answer
    stream.citations.value = detail.result.citations ?? []
    if (detail.prompt_tokens || detail.completion_tokens) {
      stream.usage.value = {
        promptTokens: detail.prompt_tokens,
        completionTokens: detail.completion_tokens,
      }
    }

    // Rebuild the timeline from the persisted trace so a finished run renders exactly like a
    // live one.
    const steps: TimelineStep[] = []
    const calls: ToolCallRecord[] = []
    for (let index = 1; index <= (detail.result.steps ?? 0); index += 1) {
      steps.push({ step: index, phase: 'reasoning', status: 'start', producedToolCalls: false })
      steps.push({ step: index, phase: 'reasoning', status: 'end', producedToolCalls: true })
    }
    for (const [index, invocation] of (detail.result.tool_invocations ?? []).entries()) {
      calls.push({
        step: invocation.step,
        name: invocation.name,
        callId: `${detail.id}-${index}`,
        args: invocation.arguments,
        ok: invocation.ok,
        durationMs: invocation.duration_ms,
        preview: null,
      })
    }
    stream.steps.value = steps
    stream.toolCalls.value = calls
    stream.status.value = detail.status === 'succeeded' ? 'done' : 'failed'
  } catch (error) {
    submitError.value = (error as Error).message
  } finally {
    openingRunId.value = null
  }
}

const totalTokens = computed(() => {
  const usage = stream.usage.value
  return usage ? usage.promptTokens + usage.completionTokens : 0
})

const copied = ref(false)
async function copyAnswer() {
  if (!stream.answer.value) return
  try {
    await navigator.clipboard.writeText(stream.answer.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    // fallback
  }
}

const samplePrompts = computed(() => {
  if (agentKey.value === 'compliance') {
    return [
      '审查儿童玩具商品的 CPC 认证与窒息警告合规要求',
      '检测该段文案是否存在医疗功效违禁词或绝对化用语',
      '核查移动电源等带电商品的运输及 UL 认证条款',
    ]
  }
  if (agentKey.value === 'listing_optimization') {
    return [
      '优化便携降噪蓝牙耳机的 Listing 标题与五点描述',
      '提炼防滑瑜伽垫的 SEO 高频关键词及买家痛点卖点',
      '生成一份户外露营折叠椅的 A+ 页面卖点架构',
    ]
  }
  return [
    '总结已上传文档中的核心规范与核心操作原则',
    '文档中关于售后质保和退换货政策的具体要求是什么？',
    '基于参考知识库说明当前业务的标准执行流程',
  ]
})

function applyPrompt(text: string) {
  prompt.value = text
}

function getAgentIcon(key: string): string {
  if (key === 'compliance') return '🛡️'
  if (key === 'listing_optimization') return '🚀'
  if (key === 'doc_qa') return '📚'
  return '🤖'
}
</script>

<template>
  <div class="grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)_320px] lg:items-start">
    <!-- Main Chat Workspace -->
    <section class="order-1 space-y-4 lg:order-2">
      <!-- Loading Skeleton -->
      <div v-if="loading" class="card space-y-3 p-5">
        <div class="flex gap-2">
          <div class="aw-skeleton h-7 w-36 rounded-lg" />
          <div class="aw-skeleton h-7 w-28 rounded-lg" />
        </div>
        <div class="aw-skeleton h-28 w-full rounded-xl" />
        <div class="aw-skeleton h-10 w-32 rounded-lg" />
      </div>

      <!-- Load Error -->
      <div v-else-if="loadError" class="card border-rose-500/30 p-5">
        <div class="flex items-center gap-2 text-rose-300">
          <svg class="h-4 w-4 shrink-0 text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span class="text-sm">工作台加载失败：{{ loadError }}</span>
        </div>
        <button class="btn-ghost mt-3 text-xs" @click="bootstrap">重新加载</button>
      </div>

      <!-- Agent Control & Input Card -->
      <div v-else class="card p-5 shadow-2xl">
        <!-- Visual Agent Switcher -->
        <div>
          <div class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-400">选择 Agent 角色</div>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="agent in agents"
              :key="agent.key"
              type="button"
              class="flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition-all"
              :class="agentKey === agent.key
                ? 'bg-accent-500/15 border border-accent-500/40 text-white shadow-sm shadow-accent-500/10 ring-1 ring-accent-500/20'
                : 'border border-white/[0.06] bg-ink-950/40 text-slate-400 hover:border-white/15 hover:text-slate-200'"
              @click="agentKey = agent.key"
            >
              <span class="text-sm">{{ getAgentIcon(agent.key) }}</span>
              <span>{{ agent.name }}</span>
            </button>
          </div>
        </div>

        <!-- Agent Meta Info & Badges -->
        <div v-if="activeAgent" class="mt-3.5 flex flex-wrap items-center gap-2 text-xs">
          <p class="w-full text-xs leading-relaxed text-ink-300">
            {{ activeAgent.description }}
          </p>
          <div class="mt-1 flex flex-wrap items-center gap-2">
            <NuxtLink
              to="/kb"
              class="chip transition-colors hover:border-white/20 hover:text-white"
              title="前往知识库管理文档"
            >
              📚 知识库：{{ readyDocuments.length }} 份已索引
            </NuxtLink>
            <span class="chip">
              ⚙️ 工具：{{ activeAgent.tools.join(' · ') }}
            </span>
          </div>
        </div>

        <!-- Empty KB Alert -->
        <div
          v-if="!readyDocuments.length"
          class="mt-3 flex items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-xs text-amber-200"
        >
          <div class="flex items-center gap-2">
            <svg class="h-4 w-4 shrink-0 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <span>知识库暂无已索引文档，检索与合规依据可能为空。</span>
          </div>
          <NuxtLink to="/kb" class="shrink-0 font-medium text-amber-300 underline underline-offset-2 hover:text-white">
            上传文档 →
          </NuxtLink>
        </div>

        <!-- Prompt Textarea -->
        <div class="mt-4">
          <textarea
            v-model="prompt"
            rows="4"
            class="field resize-y text-sm leading-relaxed"
            :placeholder="activeAgent?.opening_message || '描述你的问题或粘贴需要审查的商品文案…'"
            @keydown="onKeydown"
          />
        </div>

        <!-- Quick Prompt Suggestions -->
        <div class="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span class="text-[11px] font-medium text-ink-400 select-none">💡 试试提问：</span>
          <button
            v-for="item in samplePrompts"
            :key="item"
            type="button"
            class="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-1 text-[11px] text-slate-300 transition-all hover:border-accent-400/40 hover:bg-accent-500/10 hover:text-white"
            @click="applyPrompt(item)"
          >
            {{ item }}
          </button>
        </div>

        <!-- Submission Row -->
        <div class="mt-4 flex items-center gap-3 border-t border-white/[0.06] pt-3">
          <button
            class="btn-primary"
            :disabled="busy || isStreaming || !prompt.trim()"
            @click="submit"
          >
            <span v-if="busy || isStreaming" class="aw-spinner" />
            <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
            <span>{{ busy ? '正在提交…' : isStreaming ? 'Agent 运行中…' : '运行 Agent' }}</span>
          </button>

          <button
            v-if="isStreaming"
            class="btn-ghost !border-rose-500/30 !bg-rose-500/10 text-rose-300 hover:!border-rose-500/50 hover:!text-rose-200"
            @click="stream.stop()"
          >
            中断任务
          </button>

          <span class="ml-auto flex items-center gap-1 text-[11px] text-ink-400">
            <kbd class="kbd">Ctrl</kbd> / <kbd class="kbd">⌘</kbd> + <kbd class="kbd">Enter</kbd> 提交
          </span>
        </div>

        <!-- Error Notice -->
        <div
          v-if="submitError"
          class="mt-3 flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3.5 py-2.5 text-xs text-rose-300"
        >
          <svg class="h-4 w-4 shrink-0 text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span>{{ submitError }}</span>
        </div>
      </div>

      <!-- Agent Answer Display Panel -->
      <div v-if="showAnswer" class="card p-5 shadow-2xl">
        <!-- Answer Header -->
        <div class="mb-4 flex items-center justify-between border-b border-white/[0.06] pb-3 text-xs">
          <div class="flex items-center gap-2.5">
            <span class="grid h-6 w-6 place-items-center rounded-lg bg-accent-500/20 text-xs">
              {{ getAgentIcon(agentKey) }}
            </span>
            <span class="font-medium text-white">{{ activeAgent?.name || 'Agent 回复' }}</span>
            <span
              class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium"
              :class="isStreaming ? 'bg-accent-500/15 text-accent-300 border border-accent-500/30' : 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'"
            >
              <span
                class="h-1.5 w-1.5 rounded-full"
                :class="isStreaming ? 'aw-active-node bg-accent-400' : 'bg-emerald-400'"
              />
              <span v-if="isStreaming" class="aw-spinner h-2.5 w-2.5" />
              <span>{{ answerPhase }}</span>
            </span>
          </div>

          <div class="flex items-center gap-2">
            <span v-if="stream.usage.value" class="chip">
              {{ totalTokens.toLocaleString() }} tokens
            </span>
            <button
              type="button"
              class="btn-ghost !px-2.5 !py-1 text-xs"
              :disabled="!stream.answer.value"
              @click="copyAnswer"
            >
              <svg v-if="!copied" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>
                <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
              </svg>
              <svg v-else class="h-3.5 w-3.5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              <span>{{ copied ? '已复制' : '复制回答' }}</span>
            </button>
          </div>
        </div>

        <!-- Markdown Answer Content -->
        <div
          class="prose-invert max-w-none text-sm leading-relaxed text-slate-200"
          :class="{ 'aw-caret': isStreaming }"
          v-html="renderMarkdownLite(stream.answer.value)"
        />

        <!-- Error In Stream -->
        <div
          v-if="stream.errorMessage.value"
          class="mt-4 flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3.5 py-2.5 text-xs text-rose-300"
        >
          <svg class="h-4 w-4 shrink-0 text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span>{{ stream.errorMessage.value }}</span>
        </div>
      </div>
    </section>

    <!-- Right Rail: Execution Trace, Citations & Metadata -->
    <aside class="order-2 space-y-4 lg:order-3">
      <!-- Loading Skeleton -->
      <div v-if="loading" class="card space-y-3 p-5">
        <div class="aw-skeleton h-4 w-24 rounded" />
        <div class="aw-skeleton h-3 w-full rounded" />
        <div class="aw-skeleton h-3 w-3/4 rounded" />
      </div>

      <!-- Execution Timeline -->
      <div v-else class="card p-5">
        <div class="mb-3.5 flex items-center justify-between">
          <div class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-300">
            <svg class="h-4 w-4 text-accent-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
            </svg>
            <span>执行轨迹 (Trace)</span>
          </div>
          <span v-if="isStreaming" class="aw-spinner text-accent-400" />
        </div>
        <RunTimeline
          :steps="stream.steps.value"
          :tool-calls="stream.toolCalls.value"
          :active-step="stream.activeNode.value"
          :running="isStreaming"
          :tools="activeAgent?.tools ?? []"
        />
      </div>

      <!-- Citation Sources -->
      <div v-if="stream.citations.value.length" class="card p-5">
        <div class="mb-3.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-300">
          <svg class="h-4 w-4 text-indigo-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
          </svg>
          <span>知识库引用溯源 ({{ stream.citations.value.length }})</span>
        </div>
        <CitationList :citations="stream.citations.value" />
      </div>

      <!-- Run Details & Metrics -->
      <div v-if="currentRunId" class="card p-4 text-xs">
        <div class="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-ink-400">运行元数据</div>
        <div class="space-y-1.5 font-mono text-[11px]">
          <div class="flex items-center justify-between text-ink-400">
            <span>状态</span>
            <span class="rounded bg-white/[0.04] px-1.5 py-0.5 text-slate-200">{{ stream.status.value }}</span>
          </div>
          <div class="flex items-center justify-between text-ink-400">
            <span>Run ID</span>
            <span class="truncate max-w-[140px] text-slate-300" :title="currentRunId">{{ currentRunId }}</span>
          </div>
          <div class="flex items-center justify-between text-ink-400">
            <span>事件 Seq</span>
            <span class="text-slate-200">{{ stream.lastSeq.value }}</span>
          </div>
        </div>
      </div>
    </aside>

    <!-- Left Rail: Run History (Desktop Sticky) -->
    <aside class="order-3 lg:order-1 lg:sticky lg:top-20">
      <div class="card flex max-h-[70vh] flex-col p-4 shadow-xl lg:max-h-[calc(100vh-6rem)]">
        <div class="mb-3 flex items-center justify-between">
          <div class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-300">
            <svg class="h-4 w-4 text-ink-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
            </svg>
            <span>最近运行</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span v-if="historyRefreshing" class="aw-spinner text-ink-400" />
            <span v-if="history.length" class="chip">
              {{ history.length }}
            </span>
          </div>
        </div>

        <div v-if="loading" class="space-y-2">
          <div v-for="index in 4" :key="index" class="aw-skeleton h-12 w-full rounded-xl" />
        </div>

        <ul v-else-if="history.length" class="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
          <li v-for="run in history" :key="run.id">
            <button
              type="button"
              class="group flex w-full items-start gap-2.5 rounded-xl border p-2 text-left text-xs transition-all disabled:cursor-not-allowed disabled:opacity-50"
              :class="run.id === currentRunId
                ? 'border-accent-500/40 bg-accent-500/10 shadow-xs'
                : 'border-transparent bg-white/[0.02] hover:border-white/10 hover:bg-white/[0.05]'"
              :disabled="isStreaming || openingRunId !== null"
              :title="isStreaming ? '运行中，结束后可查看历史' : '查看该次运行结果与轨迹'"
              @click="openHistoricalRun(run)"
            >
              <span
                class="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                :class="STATUS_DOT[run.status] ?? 'bg-ink-500'"
              />
              <span class="min-w-0 flex-1">
                <span class="block truncate font-medium text-slate-300 group-hover:text-white">
                  {{ run.input?.text || '(空输入)' }}
                </span>
                <span class="mt-1 flex items-center gap-2 font-mono text-[10px] text-ink-400">
                  <span>{{ shortTime(run.created_at) }}</span>
                  <span v-if="run.latency_ms" class="rounded bg-white/[0.04] px-1 py-0.2">
                    {{ formatDuration(run.latency_ms) }}
                  </span>
                </span>
              </span>
              <span v-if="openingRunId === run.id" class="aw-spinner mt-1" />
            </button>
          </li>
        </ul>

        <div v-else class="py-6 text-center text-xs leading-relaxed text-ink-400">
          <div class="mx-auto mb-2 grid h-8 w-8 place-items-center rounded-full bg-white/[0.03] text-ink-500">
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
          暂无历史运行记录。提交提问后，所有执行日志与轨迹将在此留存。
        </div>
      </div>
    </aside>
  </div>
</template>
