<script setup lang="ts">
import type { ToolCallRecord, TimelineStep } from '~/composables/useRunStream'

const props = defineProps<{
  steps: TimelineStep[]
  toolCalls: ToolCallRecord[]
  activeStep: string | null
  running: boolean
  tools: string[]
}>()

type NodeState = 'running' | 'pending' | 'done' | 'failed'

interface Row {
  key: string
  step: number
  label: string
  state: NodeState
  toolCalls: ToolCallRecord[]
}

const rows = computed<Row[]>(() => {
  const grouped = new Map<number, ToolCallRecord[]>()
  for (const call of props.toolCalls) {
    const bucket = grouped.get(call.step) ?? []
    bucket.push(call)
    grouped.set(call.step, bucket)
  }

  const finished = new Set(
    props.steps.filter((item) => item.status === 'end').map((item) => item.step),
  )

  return props.steps
    .filter((item) => item.status === 'start')
    .map((start) => {
      // Only the step the stream is currently on is "running"; the rest of an in-flight run
      // is queued behind it. Once the run stops, an unfinished step really did not complete.
      let state: NodeState = 'failed'
      if (finished.has(start.step)) state = 'done'
      else if (props.activeStep === `step ${start.step}`) state = 'running'
      else if (props.running) state = 'pending'

      return {
        key: `${start.step}-${start.phase}`,
        step: start.step,
        label: `第 ${start.step} 步`,
        state,
        toolCalls: grouped.get(start.step) ?? [],
      }
    })
})

const toolSummary = computed(() => props.tools.join(' · '))
</script>

<template>
  <ol class="space-y-3.5">
    <!-- Tools mounted node -->
    <li class="relative grid grid-cols-[14px_minmax(0,1fr)] items-start gap-x-3">
      <span
        v-if="rows.length"
        class="pointer-events-none absolute left-0 top-[12px] -bottom-[24px] flex w-3.5 justify-center"
        aria-hidden="true"
      >
        <span class="w-0.5 bg-white/10" />
      </span>
      <span class="relative z-10 mt-1 h-3.5 w-3.5 rounded-full bg-emerald-500 ring-4 ring-emerald-500/15" />
      <div class="min-w-0">
        <div class="text-xs font-medium text-slate-200">挂载 Agent 工具链</div>
        <div class="mt-0.5 font-mono text-[10px] text-ink-400">{{ toolSummary || '（无）' }}</div>
      </div>
    </li>

    <li
      v-for="(row, index) in rows"
      :key="row.key"
      class="relative grid grid-cols-[14px_minmax(0,1fr)] items-start gap-x-3"
    >
      <span
        v-if="index < rows.length - 1"
        class="pointer-events-none absolute left-0 top-[12px] -bottom-[24px] flex w-3.5 justify-center"
        aria-hidden="true"
      >
        <span class="w-0.5 bg-white/10" />
      </span>
      <span
        class="relative z-10 mt-1 h-3.5 w-3.5 rounded-full transition-all"
        :class="{
          'bg-accent-500 ring-4 ring-accent-500/20': row.state === 'done',
          'aw-active-node bg-accent-400 ring-4 ring-accent-400/30': row.state === 'running',
          'bg-ink-600 ring-2 ring-white/10': row.state === 'pending',
          'bg-rose-500 ring-4 ring-rose-500/20': row.state === 'failed',
        }"
      />
      <div class="min-w-0">
        <div class="flex items-center gap-2 text-xs">
          <span class="font-medium text-slate-200">{{ row.label }}</span>
          <span
            v-if="row.state === 'running'"
            class="flex items-center gap-1.5 font-mono text-[11px] text-accent-300"
          >
            <span class="aw-spinner h-2.5 w-2.5" />思考决策中…
          </span>
          <span v-else-if="row.state === 'pending'" class="text-[11px] text-ink-400">等待调度</span>
          <span v-else-if="row.state === 'failed'" class="text-[11px] text-rose-400">步骤中断</span>
        </div>

        <div v-if="row.toolCalls.length" class="mt-2 space-y-2">
          <ToolCallCard
            v-for="call in row.toolCalls"
            :key="call.callId"
            :call="call"
            :live="row.state === 'running'"
          />
        </div>
      </div>
    </li>

    <li
      v-if="!rows.length"
      class="relative grid grid-cols-[14px_minmax(0,1fr)] items-start gap-x-3"
    >
      <span
        class="relative z-10 mt-1 h-3.5 w-3.5 rounded-full"
        :class="running ? 'aw-active-node bg-accent-400 ring-4 ring-accent-400/30' : 'bg-ink-600 ring-2 ring-white/10'"
      />
      <div class="flex items-center gap-2 text-xs text-ink-400">
        <span v-if="running" class="aw-spinner h-2.5 w-2.5 text-accent-400" />
        <span>{{ running ? '模型思考与调度中…' : '暂无执行步骤记录' }}</span>
      </div>
    </li>
  </ol>
</template>
