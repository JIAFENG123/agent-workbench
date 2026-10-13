<script setup lang="ts">
import type { ToolCallRecord } from '~/composables/useRunStream'

const props = withDefaults(
  defineProps<{ call: ToolCallRecord; live?: boolean }>(),
  { live: false },
)

const expanded = ref(false)

const pending = computed(() => props.call.ok === null && props.live)
</script>

<template>
  <div class="rounded-xl border border-white/[0.08] bg-ink-950/50 text-xs overflow-hidden transition-all hover:border-white/15">
    <button
      type="button"
      class="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-white/[0.02]"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <span
        class="h-2 w-2 shrink-0 rounded-full"
        :class="call.ok === null ? 'bg-amber-400 ring-2 ring-amber-400/20' : call.ok ? 'bg-emerald-400 ring-2 ring-emerald-400/20' : 'bg-rose-400 ring-2 ring-rose-400/20'"
      />
      <span class="truncate font-mono text-[11px] font-medium text-slate-200">{{ call.name }}</span>

      <span v-if="call.durationMs !== null" class="shrink-0 rounded bg-white/[0.04] px-1.5 py-0.2 font-mono text-[10px] text-ink-300">
        {{ call.durationMs }}ms
      </span>
      <span v-else-if="pending" class="flex shrink-0 items-center gap-1.5 font-mono text-[10px] text-amber-300">
        <span class="aw-spinner h-2.5 w-2.5" />执行中
      </span>

      <span class="ml-auto flex items-center gap-1 text-[11px] text-ink-400">
        <span>{{ expanded ? '收起' : '参数' }}</span>
        <svg
          class="h-3 w-3 transition-transform"
          :class="{ 'rotate-180': expanded }"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </span>
    </button>

    <div v-if="expanded" class="space-y-2 border-t border-white/[0.06] bg-ink-950/80 p-3">
      <div>
        <div class="mb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-400">输入参数 (Arguments)</div>
        <pre class="overflow-x-auto rounded-lg border border-white/[0.05] bg-ink-900/90 p-2.5 font-mono text-[11px] text-slate-300 leading-relaxed">{{
          JSON.stringify(call.args, null, 2)
        }}</pre>
      </div>
      <div v-if="call.preview">
        <div class="mb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-400">工具返回结果预览</div>
        <pre class="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-white/[0.05] bg-ink-900/90 p-2.5 font-mono text-[11px] text-slate-300 leading-relaxed">{{ call.preview }}</pre>
      </div>
    </div>
  </div>
</template>
