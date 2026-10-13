import type { Citation } from '~/types/api'

export interface TimelineStep {
  step: number
  phase: string
  status: 'start' | 'end'
  producedToolCalls: boolean
}

export interface ToolCallRecord {
  step: number
  name: string
  callId: string
  args: Record<string, unknown>
  ok: boolean | null
  durationMs: number | null
  preview: string | null
}

export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'done' | 'failed'

/**
 * Consumes the run's SSE stream.
 *
 * `EventSource` is deliberately not used: it cannot attach an Authorization header, and the
 * only alternative — putting the JWT in the query string — would leak it into access logs.
 * Reading the response body directly also makes `Last-Event-ID` resume possible.
 */
export function useRunStream() {
  const { token } = useAuth()
  const { apiBase } = useApi()

  const status = ref<StreamStatus>('idle')
  const answer = ref('')
  const steps = ref<TimelineStep[]>([])
  const toolCalls = ref<ToolCallRecord[]>([])
  const citations = ref<Citation[]>([])
  const usage = ref<{ promptTokens: number; completionTokens: number } | null>(null)
  const errorMessage = ref<string | null>(null)
  const lastSeq = ref(0)

  let controller: AbortController | null = null

  /** Node the graph view should light up right now. */
  const activeNode = computed(() => {
    const open = steps.value.filter((item) => item.status === 'start')
    const done = new Set(
      steps.value.filter((item) => item.status === 'end').map((item) => item.step),
    )
    const pending = open.filter((item) => !done.has(item.step))
    return pending.length ? `step ${pending[pending.length - 1]!.step}` : null
  })

  function reset(): void {
    status.value = 'idle'
    answer.value = ''
    steps.value = []
    toolCalls.value = []
    citations.value = []
    usage.value = null
    errorMessage.value = null
    lastSeq.value = 0
  }

  function stop(): void {
    controller?.abort()
    controller = null
  }

  function apply(eventName: string, payload: Record<string, unknown>): void {
    const seq = typeof payload.seq === 'number' ? payload.seq : 0
    if (seq > lastSeq.value) lastSeq.value = seq

    switch (eventName) {
      case 'token': {
        answer.value += String(payload.text ?? '')
        break
      }
      case 'step': {
        steps.value.push({
          step: Number(payload.step ?? 0),
          phase: String(payload.phase ?? 'reasoning'),
          status: payload.status === 'end' ? 'end' : 'start',
          producedToolCalls: Boolean(payload.produced_tool_calls),
        })
        break
      }
      case 'tool_call': {
        toolCalls.value.push({
          step: Number(payload.step ?? 0),
          name: String(payload.name ?? 'unknown'),
          callId: String(payload.call_id ?? ''),
          args: (payload.arguments as Record<string, unknown>) ?? {},
          ok: null,
          durationMs: null,
          preview: null,
        })
        break
      }
      case 'tool_result': {
        const callId = String(payload.call_id ?? '')
        const record = [...toolCalls.value].reverse().find((item) => item.callId === callId)
        if (record) {
          record.ok = Boolean(payload.ok)
          record.durationMs = Number(payload.duration_ms ?? 0)
          record.preview = String(payload.preview ?? '')
        }
        break
      }
      case 'citations': {
        citations.value = (payload.items as Citation[]) ?? []
        break
      }
      case 'usage': {
        usage.value = {
          promptTokens: Number(payload.prompt_tokens ?? 0),
          completionTokens: Number(payload.completion_tokens ?? 0),
        }
        break
      }
      case 'error': {
        errorMessage.value = String(payload.message ?? '未知错误')
        break
      }
      case 'run_finished': {
        status.value = payload.status === 'succeeded' ? 'done' : 'failed'
        if (payload.status !== 'succeeded' && !errorMessage.value) {
          errorMessage.value = `运行结束：${String(payload.stopped_reason ?? 'unknown')}`
        }
        break
      }
      default:
        break
    }
  }

  function consumeFrame(frame: string): void {
    let eventName = 'message'
    const dataLines: string[] = []

    for (const line of frame.split('\n')) {
      if (!line || line.startsWith(':')) continue // comments and keep-alive pings
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      let value = colon === -1 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)

      if (field === 'event') eventName = value
      else if (field === 'data') dataLines.push(value)
    }

    if (!dataLines.length) return
    try {
      apply(eventName, JSON.parse(dataLines.join('\n')) as Record<string, unknown>)
    } catch {
      // A malformed frame is not worth tearing the stream down for.
    }
  }

  async function start(runId: string): Promise<void> {
    stop()
    reset()
    controller = new AbortController()
    status.value = 'connecting'

    const headers: Record<string, string> = { Accept: 'text/event-stream' }
    if (token.value) headers.Authorization = `Bearer ${token.value}`

    let response: Response
    try {
      response = await fetch(`${apiBase.value}/api/runs/${runId}/stream`, {
        headers,
        signal: controller.signal,
      })
    } catch (error) {
      if ((error as Error).name === 'AbortError') return
      status.value = 'failed'
      errorMessage.value = `无法连接服务：${(error as Error).message}`
      return
    }

    if (!response.ok || !response.body) {
      status.value = 'failed'
      errorMessage.value =
        response.status === 401 ? '登录已过期，请重新登录' : `建立流失败（HTTP ${response.status}）`
      return
    }

    status.value = 'streaming'
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        // Normalise CRLF to LF. A trailing lone CR is left in place: when the following LF
        // arrives in the next chunk the pair is converted then.
        buffer = buffer.replace(/\r\n/g, '\n')

        let boundary = buffer.indexOf('\n\n')
        while (boundary !== -1) {
          const frame = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          consumeFrame(frame)
          boundary = buffer.indexOf('\n\n')
        }
      }

      if (status.value === 'streaming') status.value = 'done'
    } catch (error) {
      if ((error as Error).name === 'AbortError') return
      status.value = 'failed'
      errorMessage.value = `流中断：${(error as Error).message}`
    } finally {
      reader.releaseLock()
      controller = null
    }
  }

  return {
    status,
    answer,
    steps,
    toolCalls,
    citations,
    usage,
    errorMessage,
    lastSeq,
    activeNode,
    start,
    stop,
    reset,
  }
}
