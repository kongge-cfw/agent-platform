import axios from '@/utils/axios'

export interface EmbedRoleOption {
  id: number
  code: string
  name: string
}

export type EmbedMarkdownTheme =
  | 'default'
  | 'minimal'
  | 'academic'
  | 'apple'
  | 'warm'
  | 'compact'
  | 'bauhaus'
  | 'editorial'
  | 'zen'

export const EMBED_MARKDOWN_THEMES: Array<{ id: EmbedMarkdownTheme; label: string }> = [
  { id: 'default', label: '现代' },
  { id: 'minimal', label: '极简' },
  { id: 'academic', label: '学术' },
  { id: 'apple', label: '苹果' },
  { id: 'warm', label: '护眼' },
  { id: 'compact', label: '紧凑' },
  { id: 'bauhaus', label: '包豪斯' },
  { id: 'editorial', label: '日报' },
  { id: 'zen', label: '禅意' },
]

export const EMBED_THEME_COLORS = [
  '#1677ff',
  '#f97316',
  '#10b981',
  '#8b5cf6',
  '#ec4899',
  '#06b6d4',
  '#eab308',
  '#ef4444',
  '#64748b',
]

export interface EmbedChatSettings {
  enable_multi_agent: boolean
  enable_sql_plan: boolean
  expand_thoughts: boolean
  enable_grounding: boolean
  grounding_block_mode: 'strict_buffer' | 'stream_with_retraction'
  theme: 'light' | 'dark'
  primary_color: string
  markdown_theme: EmbedMarkdownTheme
  hide_message_border: boolean
  show_bash_banner: boolean
}

export const defaultEmbedChatSettings = (): EmbedChatSettings => ({
  enable_multi_agent: true,
  enable_sql_plan: false,
  expand_thoughts: true,
  enable_grounding: false,
  grounding_block_mode: 'strict_buffer',
  theme: 'light',
  primary_color: '#1677ff',
  markdown_theme: 'default',
  hide_message_border: true,
  show_bash_banner: true,
})

export interface SysEmbedApp {
  id: string
  app_key: string
  name: string
  description?: string | null
  role_id?: number | null
  role_name?: string | null
  lock_entry_agent: boolean
  default_entry_agent_id?: string | null
  default_entry_agent_name?: string | null
  allowed_origins: string[]
  require_identity: boolean
  claim_keys: string[]
  data_permission_mode: 'nanzi_sql_rewrite' | 'mcp_only'
  shortcut_prompts: Array<{ label: string; command: string; scenario?: string }>
  examples?: Array<{
    label: string
    command: string
    scenario?: string
    attachments?: Array<{ url: string; filename: string; size?: number; ext?: string }>
  }>
  chat_settings?: EmbedChatSettings | null
  is_active: boolean
  created_by?: string | null
  updated_by?: string | null
  created_at: string
  updated_at: string
}

export interface SysEmbedAppPayload {
  app_key?: string
  name: string
  description?: string
  role_id: number
  lock_entry_agent?: boolean
  default_entry_agent_id?: string | null
  allowed_origins?: string[]
  require_identity?: boolean
  claim_keys?: string[]
  data_permission_mode?: 'nanzi_sql_rewrite' | 'mcp_only'
  shortcut_prompts?: Array<{ label: string; command: string; scenario?: string }>
  examples?: Array<{
    label: string
    command: string
    scenario?: string
    attachments?: Array<{ url: string; filename: string; size?: number; ext?: string }>
  }>
  chat_settings?: EmbedChatSettings
  is_active?: boolean
}

export interface EmbedRoleAgentOption {
  id: string
  name: string
  display_name: string
  is_system?: boolean
}

export const embedAppApi = {
  list: () => axios.get<SysEmbedApp[]>('/api/portal/embed-apps'),
  roleOptions: () => axios.get<EmbedRoleOption[]>('/api/portal/embed-apps/role-options'),
  roleAgentOptions: (roleId: number) =>
    axios.get<EmbedRoleAgentOption[]>('/api/portal/embed-apps/role-agent-options', {
      params: { role_id: roleId },
    }),
  create: (data: SysEmbedAppPayload) => axios.post<SysEmbedApp>('/api/portal/embed-apps', data),
  update: (id: string, data: Partial<SysEmbedAppPayload>) =>
    axios.put<SysEmbedApp>(`/api/portal/embed-apps/${id}`, data),
  delete: (id: string) => axios.delete(`/api/portal/embed-apps/${id}`),
}
