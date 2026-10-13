<script setup lang="ts">
import type { CurrentUser, TokenResponse } from '~/types/api'

const api = useApi()
const { isAuthenticated, adopt, restore } = useAuth()

const mode = ref<'login' | 'register'>('login')
const email = ref('')
const password = ref('')
const tenantName = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

onMounted(() => {
  restore()
  if (isAuthenticated.value) navigateTo('/chat')
})

async function submit() {
  if (busy.value) return
  error.value = null
  busy.value = true
  try {
    const path = mode.value === 'login' ? '/api/auth/login' : '/api/auth/register'
    const body: Record<string, string> = {
      email: email.value.trim(),
      password: password.value,
    }
    if (mode.value === 'register' && tenantName.value.trim()) {
      body.tenant_name = tenantName.value.trim()
    }

    const result = await api.post<TokenResponse>(path, body)
    adopt(result.access_token)
    await api.get<CurrentUser>('/api/auth/me')
    await navigateTo('/chat')
  } catch (caught) {
    error.value = (caught as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="mx-auto max-w-xl py-8 sm:py-12">
    <!-- Hero Header -->
    <div class="text-center">
      <div class="inline-flex items-center gap-2 rounded-full border border-accent-500/30 bg-accent-500/10 px-3 py-1 text-xs font-medium text-accent-300 shadow-sm shadow-accent-500/10">
        <span class="relative flex h-1.5 w-1.5">
          <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-400 opacity-75" />
          <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent-400" />
        </span>
        企业级 Agent 运行时与评测基准
      </div>

      <h1 class="mt-4 text-3xl font-bold tracking-tight text-white sm:text-4xl">
        可观测 · 可评测 · 可续跑
      </h1>
      <p class="mx-auto mt-3 max-w-md text-xs sm:text-sm leading-relaxed text-ink-300">
        多 Agent 协同路由、混合 RAG 检索链路与精准引用溯源，为跨境出海与企业知识问答提供生产级支持。
      </p>

      <!-- Key Capabilities Grid -->
      <div class="mt-6 grid grid-cols-3 gap-2 text-left">
        <div class="rounded-xl border border-white/[0.06] bg-ink-900/50 p-2.5 backdrop-blur">
          <div class="text-[11px] font-semibold text-slate-200">⚡ 实时轨迹</div>
          <div class="mt-0.5 text-[10px] text-ink-400">SSE 事件流与 Tool 步骤回溯</div>
        </div>
        <div class="rounded-xl border border-white/[0.06] bg-ink-900/50 p-2.5 backdrop-blur">
          <div class="text-[11px] font-semibold text-slate-200">🔍 混合 RAG</div>
          <div class="mt-0.5 text-[10px] text-ink-400">BM25 + 向量召回与重排</div>
        </div>
        <div class="rounded-xl border border-white/[0.06] bg-ink-900/50 p-2.5 backdrop-blur">
          <div class="text-[11px] font-semibold text-slate-200">🛡️ 规则审查</div>
          <div class="mt-0.5 text-[10px] text-ink-400">带标引片段的合规诊断</div>
        </div>
      </div>
    </div>

    <!-- Auth Card -->
    <div class="card mt-8 p-6 shadow-2xl">
      <!-- Mode Switcher -->
      <div class="mb-5 flex rounded-xl border border-white/[0.08] bg-ink-950/60 p-1 text-xs">
        <button
          v-for="option in (['login', 'register'] as const)"
          :key="option"
          class="flex-1 rounded-lg py-2 font-medium transition-all"
          :class="mode === option ? 'bg-accent-500/20 text-white shadow-xs border border-accent-500/30' : 'text-slate-400 hover:text-slate-200'"
          @click="mode = option"
        >
          {{ option === 'login' ? '账号登录' : '新租户注册' }}
        </button>
      </div>

      <form class="space-y-4" @submit.prevent="submit">
        <div>
          <label for="email" class="mb-1.5 block text-xs font-medium text-slate-300">电子邮箱</label>
          <div class="relative">
            <input
              id="email"
              v-model="email"
              type="email"
              required
              autocomplete="email"
              class="field pl-9"
              placeholder="name@company.com"
            />
            <svg class="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect width="20" height="16" x="2" y="4" rx="2"/>
              <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>
            </svg>
          </div>
        </div>

        <div>
          <label for="password" class="mb-1.5 flex items-center justify-between text-xs font-medium text-slate-300">
            <span>登录密码</span>
            <span v-if="mode === 'register'" class="text-[11px] text-ink-400 font-normal">至少 8 位字符</span>
          </label>
          <div class="relative">
            <input
              id="password"
              v-model="password"
              type="password"
              required
              :minlength="mode === 'register' ? 8 : undefined"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              class="field pl-9"
              placeholder="••••••••"
            />
            <svg class="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
          </div>
        </div>

        <div v-if="mode === 'register'">
          <label for="tenant" class="mb-1.5 block text-xs font-medium text-slate-300">
            工作区名称 <span class="font-normal text-ink-400">（可选）</span>
          </label>
          <div class="relative">
            <input
              id="tenant"
              v-model="tenantName"
              type="text"
              class="field pl-9"
              placeholder="默认基于邮箱前缀生成"
            />
            <svg class="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 21h18"/>
              <path d="M19 21v-4"/>
              <path d="M19 13V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v14"/>
              <path d="M9 9h1"/>
              <path d="M9 13h1"/>
              <path d="M14 9h1"/>
              <path d="M14 13h1"/>
            </svg>
          </div>
        </div>

        <div v-if="error" class="flex items-center gap-2 rounded-lg border border-rose-500/20 bg-rose-500/10 px-3.5 py-2.5 text-xs text-rose-300">
          <svg class="h-4 w-4 shrink-0 text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span>{{ error }}</span>
        </div>

        <button type="submit" class="btn-primary !py-2.5 w-full text-sm font-semibold" :disabled="busy">
          <span v-if="busy" class="aw-spinner" />
          <span>{{ busy ? '正在验证…' : mode === 'login' ? '立即登录进入工作台' : '创建账号并开启工作区' }}</span>
        </button>
      </form>

      <div class="mt-5 flex items-center justify-center gap-2 border-t border-white/[0.06] pt-4 text-center text-[11px] text-ink-400">
        <svg class="h-3.5 w-3.5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        <span>多租户安全隔离 · 知识库与运行记录完全私有</span>
      </div>
    </div>
  </div>
</template>
