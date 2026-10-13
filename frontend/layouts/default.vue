<script setup lang="ts">
import type { CurrentUser, HealthResponse } from '~/types/api'

const { user, token, isAuthenticated, restore, clear } = useAuth()
const api = useApi()

const waking = ref(false)
const health = ref<HealthResponse | null>(null)
const healthError = ref<string | null>(null)

const links = [
  { to: '/chat', label: '对话' },
  { to: '/kb', label: '知识库' },
]

async function loadUser() {
  if (!token.value || user.value) return
  try {
    user.value = await api.get<CurrentUser>('/api/auth/me')
  } catch {
    clear()
  }
}

/**
 * Render's free tier sleeps after 15 minutes idle and pays a 30-60s cold start on the next
 * request. Rather than let that look like a hang, the shell says so explicitly — and the
 * keepalive workflow keeps it rare.
 */
async function checkHealth() {
  const slowTimer = window.setTimeout(() => {
    waking.value = true
  }, 3000)

  try {
    health.value = await api.get<HealthResponse>('/healthz')
    healthError.value = null
  } catch (error) {
    healthError.value = (error as Error).message
  } finally {
    window.clearTimeout(slowTimer)
    waking.value = false
  }
}

onMounted(async () => {
  restore()
  await Promise.all([loadUser(), checkHealth()])
})

function signOut() {
  clear()
  navigateTo('/')
}

const statusTone = computed(() => {
  if (healthError.value) return 'bg-rose-500'
  if (!health.value) return 'bg-amber-400'
  if (health.value.status === 'ok') return 'bg-emerald-500'
  return 'bg-amber-400'
})

const statusLabel = computed(() => {
  if (healthError.value) return 'API 不可达'
  if (!health.value) return '检测中'
  const parts = [health.value.database ? 'DB 正常' : 'DB 异常']
  if (!health.value.llm_configured) parts.push('未配置模型 Key')
  return parts.join(' · ')
})
</script>

<template>
  <div class="flex min-h-screen flex-col selection:bg-accent-500/30 selection:text-white">
    <header class="sticky top-0 z-30 border-b border-white/[0.07] bg-ink-950/80 backdrop-blur-xl transition-all">
      <div class="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <!-- Brand Logo -->
        <NuxtLink to="/chat" class="group flex items-center gap-2.5 transition-transform active:scale-[0.98]">
          <img
            src="/favicon.svg"
            alt="AW Logo"
            class="h-8 w-8 rounded-xl shadow-md shadow-accent-500/25 ring-1 ring-white/20 transition-all group-hover:shadow-accent-500/40"
          />
          <div class="flex items-center gap-2">
            <span class="font-semibold tracking-tight text-white group-hover:text-slate-100">Agent Workbench</span>
            <span class="hidden rounded-full border border-accent-500/25 bg-accent-500/10 px-2 py-0.5 font-mono text-[10px] font-medium text-accent-300 sm:inline">PRO</span>
          </div>
        </NuxtLink>

        <!-- Navigation Pills -->
        <nav v-if="isAuthenticated" class="flex items-center gap-1 text-sm">
          <NuxtLink
            to="/chat"
            class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-slate-400 transition-all hover:bg-white/[0.04] hover:text-white"
            active-class="!bg-white/[0.08] !text-white shadow-xs border border-white/[0.08]"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            对话
          </NuxtLink>
          <NuxtLink
            to="/kb"
            class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-slate-400 transition-all hover:bg-white/[0.04] hover:text-white"
            active-class="!bg-white/[0.08] !text-white shadow-xs border border-white/[0.08]"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"/>
              <path d="M6 6h10"/>
              <path d="M6 10h10"/>
            </svg>
            知识库
          </NuxtLink>
        </nav>

        <!-- Right Side: Status & User Profile -->
        <div class="ml-auto flex items-center gap-3 text-xs">
          <!-- Hardware Status Pill -->
          <div class="hidden items-center gap-2 rounded-full border border-white/[0.08] bg-ink-900/60 px-2.5 py-1 text-[11px] text-slate-300 backdrop-blur md:flex">
            <span class="relative flex h-2 w-2">
              <span
                class="absolute inline-flex h-full w-full rounded-full opacity-75"
                :class="[statusTone, health?.status === 'ok' ? 'animate-ping' : '']"
              />
              <span class="relative inline-flex h-2 w-2 rounded-full" :class="statusTone" />
            </span>
            <span class="font-mono text-ink-300">{{ statusLabel }}</span>
          </div>

          <!-- User Info & Avatar -->
          <div v-if="user" class="hidden items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.03] px-2.5 py-1 text-slate-300 sm:flex">
            <span class="grid h-5 w-5 place-items-center rounded-full bg-accent-500/20 font-mono text-[10px] font-semibold text-accent-300">
              {{ user.email.slice(0, 1).toUpperCase() }}
            </span>
            <span class="max-w-[120px] truncate text-[11px]">{{ user.email }}</span>
          </div>

          <button
            v-if="isAuthenticated"
            class="btn-ghost !px-2.5 !py-1 text-xs"
            title="退出登录"
            @click="signOut"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
              <polyline points="16 17 21 12 16 7"/>
              <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
            <span class="hidden sm:inline">退出</span>
          </button>
        </div>
      </div>
    </header>

    <!-- Cold Start Wake Banner -->
    <div
      v-if="waking"
      class="flex items-center justify-center gap-2 border-b border-amber-500/20 bg-amber-500/10 px-4 py-2 text-center text-xs text-amber-200 backdrop-blur"
    >
      <span class="aw-spinner text-amber-400" />
      <span>正在连接服务后端，请稍候…</span>
    </div>

    <main class="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
      <slot />
    </main>
  </div>
</template>
