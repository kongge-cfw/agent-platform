import axios from '@/utils/axios'

export interface EmbedRoleOption {
  id: number
  code: string
  name: string
}

export interface SysEmbedApp {
  id: string
  app_key: string
  name: string
  description?: string | null
  role_id?: number | null
  role_name?: string | null
  lock_entry_agent: boolean
  allowed_origins: string[]
  require_identity: boolean
  claim_keys: string[]
  data_permission_mode: 'nanzi_sql_rewrite' | 'mcp_only'
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
  allowed_origins?: string[]
  require_identity?: boolean
  claim_keys?: string[]
  data_permission_mode?: 'nanzi_sql_rewrite' | 'mcp_only'
  is_active?: boolean
}

export const embedAppApi = {
  list: () => axios.get<SysEmbedApp[]>('/api/portal/embed-apps'),
  roleOptions: () => axios.get<EmbedRoleOption[]>('/api/portal/embed-apps/role-options'),
  create: (data: SysEmbedAppPayload) => axios.post<SysEmbedApp>('/api/portal/embed-apps', data),
  update: (id: string, data: Partial<SysEmbedAppPayload>) =>
    axios.put<SysEmbedApp>(`/api/portal/embed-apps/${id}`, data),
  delete: (id: string) => axios.delete(`/api/portal/embed-apps/${id}`),
}
