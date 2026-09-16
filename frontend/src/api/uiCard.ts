import axios from '@/utils/axios'

export interface SysUiCard {
  id: string
  card_key: string
  name: string
  description?: string | null
  render_type: string
  url: string
  allowed_origins: string[]
  allowed_actions: string[]
  allowed_agent_ids: string[]
  default_height: number
  token_ttl_seconds: number
  is_active: boolean
  created_by?: string | null
  updated_by?: string | null
  created_at: string
  updated_at: string
}

export interface SysUiCardPayload {
  card_key: string
  name: string
  description?: string
  render_type?: string
  url: string
  allowed_origins?: string[]
  allowed_actions: string[]
  allowed_agent_ids?: string[]
  default_height?: number
  token_ttl_seconds?: number
  is_active?: boolean
}

export const uiCardApi = {
  list: () => axios.get<SysUiCard[]>('/api/portal/ui-cards'),
  create: (data: SysUiCardPayload) => axios.post<SysUiCard>('/api/portal/ui-cards', data),
  update: (id: string, data: Partial<SysUiCardPayload>) =>
    axios.put<SysUiCard>(`/api/portal/ui-cards/${id}`, data),
  delete: (id: string) => axios.delete(`/api/portal/ui-cards/${id}`),
}
