import axios from '@/utils/axios'

export interface SysEmbedApp {
  id: string
  app_key: string
  name: string
  description?: string | null
  allowed_agent_ids: string[]
  allowed_origins: string[]
  require_identity: boolean
  claim_keys: string[]
  create_shadow_user: boolean
  data_permission_mode: 'nanzi_sql_rewrite' | 'mcp_only'
  isolate_datasets_by_tenant: boolean
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
  allowed_agent_ids?: string[]
  allowed_origins?: string[]
  require_identity?: boolean
  claim_keys?: string[]
  create_shadow_user?: boolean
  data_permission_mode?: 'nanzi_sql_rewrite' | 'mcp_only'
  isolate_datasets_by_tenant?: boolean
  is_active?: boolean
}

export const embedAppApi = {
  list: () => axios.get<SysEmbedApp[]>('/api/portal/embed-apps'),
  create: (data: SysEmbedAppPayload) => axios.post<SysEmbedApp>('/api/portal/embed-apps', data),
  update: (id: string, data: Partial<SysEmbedAppPayload>) =>
    axios.put<SysEmbedApp>(`/api/portal/embed-apps/${id}`, data),
  delete: (id: string) => axios.delete(`/api/portal/embed-apps/${id}`),
}
