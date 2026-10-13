const ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

export function escapeHtml(source: string): string {
  return source.replace(/[&<>"']/g, (character) => ESCAPES[character] ?? character)
}

/**
 * Minimal, deliberately non-configurable markdown renderer.
 *
 * Everything is HTML-escaped *before* any tags are introduced, so model output can never
 * inject markup — the only tags in the result are the ones added here. A full markdown
 * library is overkill for the handful of constructs the agent prompts actually emit.
 */
export function renderMarkdownLite(source: string): string {
  const escaped = escapeHtml(source)

  return escaped
    .replace(/^###\s+(.+)$/gm, '<h3 class="mt-4 mb-1.5 text-sm font-semibold tracking-tight text-white flex items-center gap-1.5"><span class="h-1.5 w-1.5 rounded-full bg-accent-400"></span>$1</h3>')
    .replace(/^##\s+(.+)$/gm, '<h2 class="mt-5 mb-2 text-base font-semibold tracking-tight text-white">$1</h2>')
    .replace(/^#\s+(.+)$/gm, '<h1 class="mt-6 mb-3 text-lg font-bold tracking-tight text-white">$1</h1>')
    .replace(/^&gt;\s+(.+)$/gm, '<blockquote class="my-2 border-l-2 border-accent-500/60 pl-3 py-0.5 text-xs italic text-slate-300 bg-accent-500/5 rounded-r">$1</blockquote>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong class="font-semibold text-white">$1</strong>')
    .replace(/`([^`\n]+)`/g, '<code class="rounded bg-ink-800/90 border border-white/10 px-1.5 py-0.5 font-mono text-[11px] text-accent-300">$1</code>')
    .replace(/\[(\d+)\]/g, '<span class="inline-flex items-center justify-center px-1.5 py-0.5 mx-0.5 rounded font-mono text-[10px] font-semibold bg-accent-500/15 text-accent-300 border border-accent-500/30 shadow-xs">[$1]</span>')
    .replace(/^-{1,2}\s+(.+)$/gm, '<span class="block pl-4 -indent-4 text-slate-200"><span class="text-accent-400 select-none">• </span>$1</span>')
    .replace(/^(\d+)\.\s+(.+)$/gm, '<span class="block pl-4 -indent-4 text-slate-200"><span class="text-accent-400 font-mono text-xs select-none">$1. </span>$2</span>')
    .replace(/\n/g, '<br>')
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) return `${milliseconds} ms`
  return `${(milliseconds / 1000).toFixed(2)} s`
}

export function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}
