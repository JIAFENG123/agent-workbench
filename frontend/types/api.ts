export interface Agent {
  key: string
  name: string
  description: string
  opening_message: string
  tools: string[]
  max_steps: number
}

export interface CurrentUser {
  id: string
  email: string
  tenant_id: string
  tenant_name: string
  created_at: string
}

export interface KbDocument {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  status: 'processing' | 'ready' | 'failed' | string
  error: string | null
  chunk_count: number
  created_at: string
}

export interface KbLimits {
  max_upload_bytes: number
  max_chunks_per_document: number
}

export interface Citation {
  index: number
  filename: string
  document_id: string
  chunk_id: string
  ordinal: number
  score: number
}

export interface ToolInvocation {
  step: number
  name: string
  arguments: Record<string, unknown>
  ok: boolean
  duration_ms: number
}

export interface RunResult {
  answer: string
  citations: Citation[]
  tool_invocations: ToolInvocation[]
  steps: number
  stopped_reason: string
}

export interface RunRecord {
  id: string
  agent_key: string
  status: string
  input: { text?: string }
  result: RunResult | null
  error: string | null
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  latency_ms: number
  created_at: string
  updated_at: string
}

export interface RunCreated {
  run_id: string
  status: string
  stream_url: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in_minutes: number
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  environment: string
  database: boolean
  llm_configured: boolean
  active_runs: number
  problems: string[]
}
