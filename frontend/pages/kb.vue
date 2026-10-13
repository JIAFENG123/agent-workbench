<script setup lang="ts">
import type { KbDocument, KbLimits } from '~/types/api'

const api = useApi()
const { isAuthenticated, restore } = useAuth()

const documents = ref<KbDocument[]>([])
const limits = ref<KbLimits | null>(null)
const uploading = ref(false)
const loading = ref(true)
const deletingId = ref<string | null>(null)
const error = ref<string | null>(null)
const dragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

let pollTimer: ReturnType<typeof setInterval> | null = null

const hasPending = computed(() =>
  documents.value.some((item) => item.status === 'processing' || item.status === 'pending'),
)

/** Shown before the limits call lands, so the copy never renders an empty number. */
const uploadLimitLabel = computed(() =>
  limits.value ? formatBytes(limits.value.max_upload_bytes) : '—',
)

async function loadLimits() {
  try {
    limits.value = await api.get<KbLimits>('/api/kb/limits')
  } catch {
    // The hint and the pre-check degrade quietly; the server enforces the limit regardless.
  }
}

async function load() {
  try {
    documents.value = await api.get<KbDocument[]>('/api/kb/documents')
  } catch (caught) {
    error.value = (caught as Error).message
  }
}

function schedulePolling() {
  if (pollTimer) return
  // Ingestion runs as a background task and the API has no push channel for it, so the list
  // is polled — only while something is actually in flight.
  pollTimer = setInterval(async () => {
    await load()
    if (!hasPending.value && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }, 2000)
}

async function upload(files: FileList | null) {
  const file = files?.[0]
  if (!file || uploading.value) return

  const maxBytes = limits.value?.max_upload_bytes
  if (maxBytes && file.size > maxBytes) {
    error.value =
      `「${file.name}」有 ${formatBytes(file.size)}，超过单文件上限 ${formatBytes(maxBytes)}。` +
      '请拆分或压缩后再传。'
    if (fileInput.value) fileInput.value.value = ''
    return
  }

  error.value = null
  uploading.value = true
  try {
    const form = new FormData()
    form.append('file', file)
    await api.request<KbDocument>('/api/kb/documents', { method: 'POST', body: form })
    await load()
    schedulePolling()
  } catch (caught) {
    error.value = (caught as Error).message
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onDrop(event: DragEvent) {
  dragging.value = false
  void upload(event.dataTransfer?.files ?? null)
}

async function remove(document: KbDocument) {
  if (!window.confirm(`删除「${document.filename}」及其全部索引？`)) return
  deletingId.value = document.id
  try {
    await api.del(`/api/kb/documents/${document.id}`)
    await load()
  } catch (caught) {
    error.value = (caught as Error).message
  } finally {
    deletingId.value = null
  }
}

const statusStyle: Record<string, string> = {
  ready: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  processing: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  pending: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  failed: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
}

const statusDot: Record<string, string> = {
  ready: 'bg-emerald-400',
  processing: 'bg-amber-400',
  pending: 'bg-amber-400',
  failed: 'bg-rose-400',
}

const statusLabel: Record<string, string> = {
  ready: '已索引',
  processing: '切块与嵌入中',
  pending: '排队中',
  failed: '处理失败',
}

const totalChunks = computed(() =>
  documents.value.reduce((acc, doc) => acc + (doc.chunk_count || 0), 0),
)

function getFileIcon(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase()
  if (ext === 'pdf') return '📄'
  if (ext === 'docx' || ext === 'doc') return '📝'
  if (ext === 'csv' || ext === 'json') return '📊'
  if (ext === 'md' || ext === 'markdown') return '📋'
  return '📃'
}

onMounted(async () => {
  restore()
  if (!isAuthenticated.value) {
    await navigateTo('/')
    return
  }
  loading.value = true
  await Promise.all([load(), loadLimits()])
  loading.value = false
  if (hasPending.value) schedulePolling()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-6 py-2">
    <!-- Header Row & Stats Grid -->
    <div class="space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div class="flex items-center gap-2">
            <h1 class="text-xl font-bold tracking-tight text-white">企业知识库</h1>
            <span class="chip">Hybrid RAG</span>
          </div>
          <p class="mt-1 text-xs text-ink-300">
            上传平台规则与业务规范文本，自动执行「语义切块 → 向量嵌入 → BM25 索引 → 混合重排」。
          </p>
        </div>

        <div class="flex items-center gap-2">
          <input
            ref="fileInput"
            type="file"
            class="hidden"
            accept=".txt,.md,.markdown,.pdf,.docx,.csv,.json"
            @change="upload(($event.target as HTMLInputElement).files)"
          />
          <button class="btn-primary shrink-0" :disabled="uploading" @click="fileInput?.click()">
            <span v-if="uploading" class="aw-spinner" />
            <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="17 8 12 3 7 8"/>
              <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
            <span>{{ uploading ? '正在解析上传…' : '上传新文档' }}</span>
          </button>
        </div>
      </div>

      <!-- Quick Metrics Summary -->
      <div class="grid grid-cols-3 gap-3">
        <div class="card p-3.5">
          <div class="text-[11px] font-medium text-ink-400">已入库文档</div>
          <div class="mt-1 flex items-baseline gap-1.5">
            <span class="text-xl font-bold text-white">{{ documents.length }}</span>
            <span class="text-xs text-ink-400">份</span>
          </div>
        </div>

        <div class="card p-3.5">
          <div class="text-[11px] font-medium text-ink-400">向量化切块</div>
          <div class="mt-1 flex items-baseline gap-1.5">
            <span class="text-xl font-bold text-white">{{ totalChunks.toLocaleString() }}</span>
            <span class="text-xs text-ink-400">chunks</span>
          </div>
        </div>

        <div class="card p-3.5">
          <div class="text-[11px] font-medium text-ink-400">单文件上限</div>
          <div class="mt-1 flex items-baseline gap-1.5">
            <span class="text-xl font-bold text-accent-300 font-mono">{{ uploadLimitLabel }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Modern Dropzone -->
    <div
      class="group relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 text-center transition-all"
      :class="dragging
        ? 'border-accent-400 bg-accent-500/10 shadow-lg shadow-accent-500/15'
        : 'border-white/10 bg-ink-900/40 hover:border-white/20 hover:bg-ink-900/60'"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <div class="grid h-12 w-12 place-items-center rounded-2xl bg-white/[0.04] text-slate-300 ring-1 ring-white/10 transition-transform group-hover:scale-105">
        <svg class="h-6 w-6 text-accent-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
          <path d="M12 12v9"/>
          <path d="m16 16-4-4-4 4"/>
        </svg>
      </div>

      <div class="mt-3 text-sm font-medium text-slate-200">
        拖拽文件到此处，或点击浏览选择文件
      </div>
      <div class="mt-1.5 flex flex-wrap items-center justify-center gap-1.5 text-[11px] text-ink-400">
        <span class="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px]">.txt</span>
        <span class="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px]">.md</span>
        <span class="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px]">.pdf</span>
        <span class="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px]">.docx</span>
        <span class="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px]">.csv</span>
        <span class="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px]">.json</span>
        <span class="ml-1 text-ink-500">· 自动识别 UTF-8 与 GB18030 · PDF/DOCX 自动提取文本</span>
      </div>
    </div>

    <!-- Error Alert -->
    <div
      v-if="error"
      class="flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-300"
    >
      <svg class="h-4 w-4 shrink-0 text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <span>{{ error }}</span>
    </div>

    <!-- Loading Skeleton -->
    <div v-if="loading" class="card space-y-4 p-5">
      <div v-for="index in 3" :key="index" class="flex items-center gap-3">
        <div class="aw-skeleton h-8 w-8 shrink-0 rounded-lg" />
        <div class="min-w-0 flex-1 space-y-2">
          <div class="aw-skeleton h-4 w-1/2 rounded" />
          <div class="aw-skeleton h-3 w-1/3 rounded" />
        </div>
      </div>
    </div>

    <!-- Document List Card -->
    <div v-else-if="documents.length" class="card divide-y divide-white/[0.06] overflow-hidden shadow-2xl">
      <div class="flex items-center justify-between bg-white/[0.02] px-5 py-3 text-xs font-medium text-ink-400">
        <span>已索引文档列表（{{ documents.length }}）</span>
        <span class="font-mono text-[11px]">按入库时间排序</span>
      </div>

      <div
        v-for="document in documents"
        :key="document.id"
        class="group flex items-center gap-3.5 px-5 py-3.5 transition-colors hover:bg-white/[0.02]"
      >
        <span class="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/[0.04] text-base ring-1 ring-white/10">
          {{ getFileIcon(document.filename) }}
        </span>

        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-medium text-slate-200 group-hover:text-white">
            {{ document.filename }}
          </div>
          <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-400">
            <!-- Status Badge -->
            <span
              class="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.2 text-[10px] font-medium"
              :class="statusStyle[document.status]"
            >
              <span
                class="h-1.5 w-1.5 rounded-full"
                :class="statusDot[document.status]"
              />
              <span>{{ statusLabel[document.status] ?? document.status }}</span>
            </span>

            <span class="font-mono">{{ formatBytes(document.size_bytes) }}</span>
            <span v-if="document.chunk_count" class="chip">
              {{ document.chunk_count }} chunks
            </span>
            <span class="text-ink-500">{{ formatDateTime(document.created_at) }}</span>
          </div>

          <p v-if="document.error" class="mt-1 truncate text-[11px] text-rose-400">
            {{ document.error }}
          </p>
        </div>

        <button
          class="btn-ghost !px-2.5 !py-1 text-xs text-slate-400 hover:!border-rose-500/40 hover:!bg-rose-500/10 hover:!text-rose-300"
          :disabled="deletingId === document.id"
          title="删除文档及其向量索引"
          @click="remove(document)"
        >
          <span v-if="deletingId === document.id" class="aw-spinner" />
          <svg v-else class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          </svg>
          <span class="hidden sm:inline">{{ deletingId === document.id ? '删除中…' : '删除' }}</span>
        </button>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else class="card p-8 text-center shadow-xl">
      <div class="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-white/[0.03] text-ink-400 ring-1 ring-white/10">
        <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"/>
          <path d="M6 6h10"/>
          <path d="M6 10h10"/>
        </svg>
      </div>
      <h3 class="text-sm font-semibold text-slate-200">知识库暂无文档</h3>
      <p class="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-ink-400">
        上传合规政策、上架指南或商品手册后，Agent 将自动检索知识库并提供精准的标引依据。
      </p>
    </div>
  </div>
</template>
