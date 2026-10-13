<script setup lang="ts">
import type { Citation } from '~/types/api'

defineProps<{ citations: Citation[] }>()

function normalizeScore(score: number): number {
  if (score >= 0 && score <= 1) return score
  // Calibrated sigmoid for raw logits (NVIDIA reranker logits are centered around -4.5)
  const x = (score - (-4.5)) / 1.8
  if (x >= 40) return 1
  if (x <= -40) return 0
  return 1 / (1 + Math.exp(-x))
}

function displayScore(score: number): string {
  const prob = normalizeScore(score)
  return `${(prob * 100).toFixed(1)}%`
}

function scorePercent(score: number): number {
  const prob = normalizeScore(score)
  return Math.min(100, Math.max(8, Math.round(prob * 100)))
}
</script>

<template>
  <ol class="space-y-2">
    <li
      v-for="citation in citations"
      :key="citation.chunk_id"
      class="group rounded-xl border border-white/[0.07] bg-ink-950/50 p-2.5 text-xs transition-all hover:border-white/15 hover:bg-ink-950/80"
    >
      <div class="flex items-center gap-2">
        <span class="grid h-5 w-5 shrink-0 place-items-center rounded-lg bg-accent-500/15 font-mono text-[11px] font-semibold text-accent-300 ring-1 ring-accent-500/30">
          {{ citation.index }}
        </span>
        <span class="truncate font-medium text-slate-200 group-hover:text-white" :title="citation.filename">
          {{ citation.filename }}
        </span>
        <span class="ml-auto shrink-0 chip !px-1.5 !py-0.2 text-[10px]">
          第 {{ citation.ordinal + 1 }} 段
        </span>
      </div>

      <div v-if="citation.score !== undefined && citation.score !== null" class="mt-2 flex items-center justify-between text-[10px] text-ink-400">
        <div class="flex items-center gap-1.5 font-mono">
          <span>相关度得分</span>
          <span class="font-semibold text-accent-300">{{ displayScore(citation.score) }}</span>
        </div>
        <div class="h-1.5 w-16 overflow-hidden rounded-full bg-white/[0.06]">
          <div
            class="h-full rounded-full bg-gradient-to-r from-accent-500 to-indigo-400 transition-all duration-300"
            :style="{ width: `${scorePercent(citation.score)}%` }"
          />
        </div>
      </div>
    </li>
  </ol>
</template>
