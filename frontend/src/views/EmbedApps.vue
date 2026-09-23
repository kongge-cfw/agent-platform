<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ChatBubbleLeftRightIcon,
  ChevronDownIcon,
  ClipboardDocumentIcon,
  MagnifyingGlassIcon,
  PencilSquareIcon,
  PlayIcon,
  PlusIcon,
  QuestionMarkCircleIcon,
  TrashIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { CheckIcon } from '@heroicons/vue/20/solid'
import { EMBED_MARKDOWN_THEMES, EMBED_THEME_COLORS, defaultEmbedChatSettings, embedAppApi, type EmbedChatSettings, type EmbedRoleAgentOption, type EmbedRoleOption, type SysEmbedApp, type SysEmbedAppPayload } from '../api/embedApp'
import ConfirmModal from '../components/ConfirmModal.vue'
import Switch from '../components/Switch.vue'
import { useToast } from '../composables/useToast'
import { useUser } from '../composables/useUser'
import axios from '../utils/axios'
import { withAppBase } from '../utils/appBase'
import { copyToClipboard } from '../utils/clipboard'
import { isPlatformMainAgent } from '../utils/delegationHost'

const { showToast } = useToast()
const { hasPermission, userInfo } = useUser()
const canCreate = hasPermission('element:embed_apps:create')
const canEdit = hasPermission('element:embed_apps:edit')
const canDelete = hasPermission('element:embed_apps:delete')

const ALL_CLAIM_KEYS = ['subject', 'display_name', 'dept_code', 'org_path', 'tenant_id', 'extra_data']
const PERMISSION_OPTIONS = [
  { value: 'nanzi_sql_rewrite', label: '平台改写 SQL 行级', hint: '由平台按业务身份改写行级过滤' },
  { value: 'mcp_only', label: '不下改写，交给业务 MCP', hint: '数据权限完全交给业务 MCP' },
] as const
const STATUS_TABS: Array<{ value: 'all' | 'active' | 'inactive'; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '启用' },
  { value: 'inactive', label: '停用' },
]
const FIELD_HINTS = {
  appKey: '保存后自动生成，签发 Ticket 时传入，不可修改',
  active: '关闭后无法签发新 Ticket',
  role: '必选。iframe 里能用的智能体，以该角色在「角色管理」中的智能体资产为准。签发 Ticket 的服务账号也需要属于这个角色。',
  host: '选中的智能体作为 iframe 智能委派宿主，可把任务委派给该角色下其他专家。未指定则不能智能委派（单个专家直达，多个需手选）。若要用平台主助手委派，请在此选中它。',
  lock: '开启后 iframe 不能切换/智能委派。Ticket 未传 agent_id 时使用上方智能委派宿主；两者都空则签发失败。工作台场景请保持关闭。',
  identity: '关闭后仍可用旧的南孜用户名代客，生产环境建议保持开启',
  origins: '每行一个，空则不限制',
} as const
type FieldHintKey = keyof typeof FIELD_HINTS

const apps = ref<SysEmbedApp[]>([])
const roles = ref<EmbedRoleOption[]>([])
const loading = ref(false)
const searchQuery = ref('')
const statusFilter = ref<'all' | 'active' | 'inactive'>('all')
const showModal = ref(false)
const isEditing = ref(false)
const showDeleteConfirm = ref(false)
const deletingApp = ref<SysEmbedApp | null>(null)
const saving = ref(false)
const showPromptModal = ref(false)
const promptApp = ref<SysEmbedApp | null>(null)
const promptDraft = ref<Array<{ label: string; command: string }>>([])
const savingPrompts = ref(false)
const openMenu = ref<'' | 'mode' | 'role' | 'host'>('')
const openHint = ref<FieldHintKey | ''>('')
const hintPos = ref({ top: 0, left: 0 })
const menuPos = ref({ top: 0, left: 0, width: 0, maxHeight: 240, openUp: false })
const windowWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const isMobile = computed(() => windowWidth.value < 1024)

type AppForm = SysEmbedAppPayload & {
  id?: string
  originsText: string
  role_id: number | '' | null
  chat_settings: EmbedChatSettings
}

const emptyForm = (): AppForm => ({
  name: '',
  description: '',
  role_id: '',
  lock_entry_agent: false,
  default_entry_agent_id: '',
  allowed_origins: [],
  require_identity: true,
  data_permission_mode: 'nanzi_sql_rewrite',
  chat_settings: defaultEmbedChatSettings(),
  is_active: true,
  originsText: '',
})

const form = ref<AppForm>(emptyForm())
const roleAgents = ref<EmbedRoleAgentOption[]>([])
const isMainRoleAgent = (agent: EmbedRoleAgentOption) => isPlatformMainAgent(agent)

const inputClass =
  'h-10 w-full rounded-xl border border-gray-200 bg-gray-50/70 px-3 text-sm text-gray-900 placeholder:text-gray-400 outline-none transition-all hover:border-gray-300 focus:border-primary focus:bg-white focus:ring-4 focus:ring-primary/10 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100'
const selectButtonClass =
  'flex h-10 w-full items-center justify-between gap-2 rounded-xl border border-gray-200 bg-gray-50/70 px-3 text-left text-sm outline-none transition-all hover:border-gray-300 focus:border-primary focus:bg-white focus:ring-4 focus:ring-primary/10 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400 dark:border-gray-700 dark:bg-gray-950'
const labelClass = 'mb-1.5 flex items-center gap-1 text-[13px] font-medium text-gray-600 dark:text-gray-300'
const hintBtnClass = 'inline-flex h-4 w-4 items-center justify-center rounded-full text-gray-300 transition-colors hover:bg-primary/10 hover:text-primary'
const menuClass = 'fixed z-[10050] overflow-y-auto rounded-xl border border-gray-100 bg-white py-1.5 shadow-xl ring-1 ring-black/5 dark:border-gray-700 dark:bg-gray-900'
const menuItemClass = 'flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors hover:bg-gray-50 dark:hover:bg-gray-800'
const sectionTitleClass = 'mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-100'

const fetchRoleAgentOptions = async (roleId: number | string | null | undefined) => {
  const parsed = Number(roleId)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    roleAgents.value = []
    return
  }
  try {
    const res = await embedAppApi.roleAgentOptions(parsed)
    roleAgents.value = Array.isArray(res.data) ? res.data : ((res.data as any)?.data || [])
  } catch {
    roleAgents.value = []
  }
  const current = String(form.value.default_entry_agent_id || '').trim()
  if (current && !roleAgents.value.some((agent) => agent.id === current || agent.name === current)) {
    form.value.default_entry_agent_id = ''
  }
}

watch(() => form.value.role_id, (roleId) => {
  if (!showModal.value) return
  void fetchRoleAgentOptions(roleId)
})

watch(showModal, (visible) => {
  if (!visible) {
    openMenu.value = ''
    openHint.value = ''
  }
})

const filteredApps = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  return apps.value.filter((app) => {
    const matchesKeyword = !keyword
      || [
        app.app_key,
        app.name,
        app.description,
        app.role_name,
        app.default_entry_agent_name,
        ...(app.allowed_origins || []),
      ].some((value) => String(value || '').toLowerCase().includes(keyword))
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'active' && app.is_active)
      || (statusFilter.value === 'inactive' && !app.is_active)
    return matchesKeyword && matchesStatus
  })
})

const isSearchEmpty = computed(() => !filteredApps.value.length && Boolean(searchQuery.value.trim() || statusFilter.value !== 'all'))

const selectedRole = computed(() => roles.value.find((role) => Number(role.id) === Number(form.value.role_id)) || null)
const selectedPermission = computed(
  () => PERMISSION_OPTIONS.find((item) => item.value === form.value.data_permission_mode) || PERMISSION_OPTIONS[0],
)
const selectedHost = computed(() => {
  const current = String(form.value.default_entry_agent_id || '').trim()
  if (!current) return null
  return roleAgents.value.find((agent) => agent.id === current || agent.name === current) || null
})

const fetchApps = async () => {
  loading.value = true
  try {
    const res = await embedAppApi.list()
    apps.value = Array.isArray(res.data) ? res.data : ((res.data as any)?.data || [])
  } catch {
    showToast('加载嵌入应用失败', 'error')
  } finally {
    loading.value = false
  }
}

const fetchRoles = async () => {
  try {
    const res = await embedAppApi.roleOptions()
    roles.value = Array.isArray(res.data) ? res.data : ((res.data as any)?.data || [])
  } catch {
    roles.value = []
  }
}

const linesToList = (text: string) => text.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)

const placeMenu = (event: MouseEvent) => {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const gap = 6
  const spaceBelow = window.innerHeight - rect.bottom - 12
  const spaceAbove = rect.top - 12
  const openUp = spaceBelow < 180 && spaceAbove > spaceBelow
  menuPos.value = {
    top: openUp ? rect.top - gap : rect.bottom + gap,
    left: rect.left,
    width: Math.max(rect.width, 220),
    maxHeight: Math.max(140, Math.min(280, openUp ? spaceAbove - gap : spaceBelow - gap)),
    openUp,
  }
}

const toggleMenu = (menu: 'mode' | 'role' | 'host', event: MouseEvent) => {
  event.preventDefault()
  event.stopPropagation()
  openHint.value = ''
  if (openMenu.value === menu) {
    openMenu.value = ''
    return
  }
  placeMenu(event)
  openMenu.value = menu
}

const placeHint = (event: MouseEvent) => {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const width = 288
  hintPos.value = {
    top: rect.bottom + 6,
    left: Math.min(Math.max(8, rect.left - 12), window.innerWidth - width - 8),
  }
}

const toggleHint = (key: FieldHintKey, event: MouseEvent) => {
  event.preventDefault()
  event.stopPropagation()
  openMenu.value = ''
  if (openHint.value === key) {
    openHint.value = ''
    return
  }
  placeHint(event)
  openHint.value = key
}

const closeMenus = () => {
  openMenu.value = ''
  openHint.value = ''
}

const openModal = (app?: SysEmbedApp) => {
  openMenu.value = ''
  openHint.value = ''
  if (app) {
    isEditing.value = true
    form.value = {
      id: app.id,
      app_key: app.app_key,
      name: app.name,
      description: app.description || '',
      role_id: app.role_id ?? '',
      lock_entry_agent: Boolean(app.lock_entry_agent),
      default_entry_agent_id: app.default_entry_agent_id || '',
      allowed_origins: [...(app.allowed_origins || [])],
      require_identity: app.require_identity !== false,
      data_permission_mode: app.data_permission_mode || 'nanzi_sql_rewrite',
      chat_settings: { ...defaultEmbedChatSettings(), ...(app.chat_settings || {}) },
      is_active: app.is_active !== false,
      originsText: (app.allowed_origins || []).join('\n'),
    }
  } else {
    isEditing.value = false
    form.value = emptyForm()
  }
  showModal.value = true
  void fetchRoleAgentOptions(form.value.role_id)
}

const onPrimaryColorInput = (event: Event) => {
  const value = (event.target as HTMLInputElement).value
  if (/^#[0-9a-fA-F]{6}$/.test(value)) form.value.chat_settings.primary_color = value
}

const copyAppKey = async (key?: string) => {
  const value = String(key || '').trim()
  if (!value) return
  const ok = await copyToClipboard(value)
  showToast(ok ? '已复制应用 Key' : '复制失败', ok ? 'success' : 'error')
}

const saveApp = async () => {
  if (!form.value.name?.trim()) {
    showToast('请填写名称', 'warning')
    return
  }
  const rawRole = form.value.role_id as number | string | null | undefined
  const parsedRole = rawRole === null || rawRole === undefined || rawRole === '' ? null : Number(rawRole)
  if (!Number.isFinite(parsedRole) || Number(parsedRole) <= 0) {
    showToast('请选择关联角色', 'warning')
    return
  }
  const payload: SysEmbedAppPayload = {
    name: form.value.name.trim(),
    description: form.value.description?.trim() || undefined,
    role_id: Number(parsedRole),
    lock_entry_agent: Boolean(form.value.lock_entry_agent),
    default_entry_agent_id: String(form.value.default_entry_agent_id || '').trim() || null,
    allowed_origins: linesToList(form.value.originsText),
    require_identity: form.value.require_identity !== false,
    claim_keys: [...ALL_CLAIM_KEYS],
    data_permission_mode: form.value.data_permission_mode || 'nanzi_sql_rewrite',
    chat_settings: { ...defaultEmbedChatSettings(), ...(form.value.chat_settings || {}) },
    is_active: form.value.is_active !== false,
  }
  saving.value = true
  try {
    if (isEditing.value && form.value.id) {
      await embedAppApi.update(form.value.id, payload)
      showToast('嵌入应用已更新', 'success')
    } else {
      const res = await embedAppApi.create(payload)
      const created = (res.data as any)?.data || res.data
      const createdKey = String(created?.app_key || '').trim()
      if (createdKey) {
        await copyToClipboard(createdKey)
        showToast(`已创建，应用 Key：${createdKey}（已复制）`, 'success')
      } else {
        showToast('嵌入应用已创建', 'success')
      }
    }
    showModal.value = false
    await fetchApps()
  } catch (error: any) {
    const detail = error.response?.data?.detail
    const message = Array.isArray(detail)
      ? detail.map((item: any) => item.msg || item).join('; ')
      : (detail || '保存失败')
    showToast(String(message), 'error')
  } finally {
    saving.value = false
  }
}

const debugApp = ref<SysEmbedApp | null>(null)
const debugFrameSrc = ref('')
const debuggingKey = ref('')

const ticketErrorMessage = (error: any, fallback: string) => {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map((item: any) => item.msg || item).join('; ')
  }
  if (typeof detail === 'string' && detail.trim()) return detail
  const message = error?.response?.data?.message
  if (typeof message === 'string' && message.trim() && message !== 'success') return message
  return error?.message || fallback
}

const openEmbedDebug = async (app: SysEmbedApp) => {
  if (!app.is_active) {
    showToast('应用已停用，无法调试', 'warning')
    return
  }
  if (debuggingKey.value) return
  debuggingKey.value = app.app_key
  try {
    const payload: Record<string, unknown> = {
      app_key: app.app_key,
      expires_in: 300,
    }
    if (app.lock_entry_agent && app.default_entry_agent_id) {
      payload.agent_id = app.default_entry_agent_id
    }
    if (app.require_identity) {
      const user = userInfo.value || {}
      const subject = String(user.user_name || '').trim()
      if (!subject) {
        showToast('当前账号缺少用户名，无法按业务身份签发调试票据', 'error')
        return
      }
      payload.identity = {
        subject,
        display_name: String(user.real_name || subject),
        dept_code: String(user.dept_code || ''),
        org_path: String(user.org_path || ''),
      }
    }
    const res = await axios.post('/api/v1/embed/tickets', payload)
    const ticket = res.data?.data?.ticket
    if (res.data?.code !== 200 || !ticket) {
      throw new Error(res.data?.message || '签发调试票据失败')
    }
    debugApp.value = app
    debugFrameSrc.value = withAppBase(`/embed/chat?ticket=${encodeURIComponent(ticket)}`)
  } catch (error: any) {
    showToast(String(ticketErrorMessage(error, '签发调试票据失败')), 'error')
  } finally {
    debuggingKey.value = ''
  }
}

const closeEmbedDebug = () => {
  debugApp.value = null
  debugFrameSrc.value = ''
}

const openPromptModal = (app: SysEmbedApp) => {
  promptApp.value = app
  const items = (app.shortcut_prompts || []).map((item) => ({
    label: String(item.label || ''),
    command: String(item.command || ''),
  }))
  promptDraft.value = items.length ? items : [{ label: '', command: '' }]
  showPromptModal.value = true
}

const addPromptRow = () => {
  if (promptDraft.value.length >= 20) return
  promptDraft.value.push({ label: '', command: '' })
}

const removePromptRow = (index: number) => {
  promptDraft.value.splice(index, 1)
  if (!promptDraft.value.length) promptDraft.value.push({ label: '', command: '' })
}

const savePrompts = async () => {
  if (!promptApp.value) return
  const incomplete = promptDraft.value.some((item) => {
    const label = String(item.label || '').trim()
    const command = String(item.command || '').trim()
    return Boolean(label) !== Boolean(command)
  })
  if (incomplete) {
    showToast('请完整填写名称和内容，或删除未填完的行', 'warning')
    return
  }
  const shortcut_prompts = promptDraft.value
    .map((item) => ({
      label: String(item.label || '').trim(),
      command: String(item.command || '').trim(),
    }))
    .filter((item) => item.label && item.command)
  savingPrompts.value = true
  try {
    await embedAppApi.update(promptApp.value.id, { shortcut_prompts })
    showToast('常用提示词已保存', 'success')
    showPromptModal.value = false
    promptApp.value = null
    await fetchApps()
  } catch (error: any) {
    const detail = error.response?.data?.detail
    const message = Array.isArray(detail)
      ? detail.map((item: any) => item.msg || item).join('; ')
      : (detail || '保存失败')
    showToast(String(message), 'error')
  } finally {
    savingPrompts.value = false
  }
}

const confirmDelete = async () => {
  if (!deletingApp.value) return
  try {
    await embedAppApi.delete(deletingApp.value.id)
    showToast('已删除', 'success')
    showDeleteConfirm.value = false
    deletingApp.value = null
    await fetchApps()
  } catch (error: any) {
    showToast(error.response?.data?.detail || '删除失败', 'error')
  }
}

const hostLabel = (app: SysEmbedApp) => {
  const name = String(app.default_entry_agent_name || '').trim()
  if (name) return name
  return String(app.default_entry_agent_id || '').trim() ? '已指定宿主' : ''
}

const permissionLabel = (app: SysEmbedApp) =>
  app.data_permission_mode === 'mcp_only' ? '权限下沉 MCP' : '平台 SQL 改写'

const originLabel = (app: SysEmbedApp) => {
  const count = app.allowed_origins?.length || 0
  return count ? `${count} 个域名` : '不限域名'
}

const resetFilters = () => {
  searchQuery.value = ''
  statusFilter.value = 'all'
}

const onResize = () => {
  windowWidth.value = window.innerWidth
}

const onDebugKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape' && debugApp.value) closeEmbedDebug()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  document.addEventListener('click', closeMenus)
  document.addEventListener('keydown', onDebugKeydown)
  void fetchApps()
  void fetchRoles()
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  document.removeEventListener('click', closeMenus)
  document.removeEventListener('keydown', onDebugKeydown)
})
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
      <div class="min-w-0">
        <h1 class="text-xl font-bold text-gray-900 sm:text-2xl dark:text-gray-100">嵌入应用</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          登记要嵌入对话组件的宿主系统。智能体范围跟角色走，保存后自动生成应用 Key，宿主签发 Ticket 时带上即可。
        </p>
      </div>
      <div class="flex flex-col gap-2.5 sm:flex-row sm:items-center">
        <div class="relative w-full sm:w-64 lg:w-72">
          <span class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
            <MagnifyingGlassIcon class="h-4 w-4 text-gray-400" />
          </span>
          <input
            v-model="searchQuery"
            type="search"
            placeholder="搜索应用 Key、名称或域名..."
            class="w-full rounded-lg border border-gray-300 bg-white py-2 pl-9 pr-3 text-sm shadow-sm outline-none transition-all focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-gray-700 dark:bg-gray-950"
          />
        </div>
        <div class="inline-flex shrink-0 self-start rounded-lg border border-gray-300 bg-white p-0.5 shadow-sm dark:border-gray-700 dark:bg-gray-950">
          <button
            v-for="item in STATUS_TABS"
            :key="item.value"
            type="button"
            class="rounded-md px-3 py-1.5 text-sm transition-colors"
            :class="statusFilter === item.value ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900' : 'text-gray-600 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-800'"
            @click="statusFilter = item.value"
          >{{ item.label }}</button>
        </div>
        <button
          v-if="canCreate"
          type="button"
          class="inline-flex shrink-0 items-center justify-center gap-2 self-start rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-dark"
          @click="openModal()"
        >
          <PlusIcon class="h-4 w-4" />
          登记应用
        </button>
      </div>
    </div>

    <div v-if="loading" class="flex flex-col items-center justify-center py-16">
      <div class="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent"></div>
      <p class="mt-4 text-sm font-medium text-gray-500">加载嵌入应用...</p>
    </div>

    <div
      v-else-if="!filteredApps.length"
      class="flex min-h-[320px] flex-col items-center justify-center rounded-lg border border-gray-200 bg-white px-6 shadow-sm dark:border-gray-800 dark:bg-gray-900"
    >
      <svg class="h-14 w-14 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 5a2 2 0 012-2h12a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm4 4h8M8 13h5" />
      </svg>
      <template v-if="isSearchEmpty">
        <p class="mt-4 text-sm font-semibold text-gray-500">无匹配的嵌入应用</p>
        <p class="mt-1 text-xs text-gray-400">试试其他关键词，或清除筛选后浏览全部</p>
        <button
          type="button"
          class="mt-5 rounded-lg border border-blue-200 px-4 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50"
          @click="resetFilters"
        >
          清除筛选
        </button>
      </template>
      <template v-else>
        <p class="mt-4 text-sm font-semibold text-gray-500">暂无嵌入应用</p>
        <p class="mt-1 text-xs text-gray-400">登记后即可用应用 Key 签发 Ticket，把对话组件嵌进业务系统</p>
        <button
          v-if="canCreate"
          type="button"
          class="mt-5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-dark"
          @click="openModal()"
        >
          登记应用
        </button>
      </template>
    </div>

    <div v-else>
      <div v-if="!isMobile" class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-800 dark:bg-gray-900">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-800">
          <thead class="bg-gray-50 dark:bg-gray-950">
            <tr>
              <th class="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">应用</th>
              <th class="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">角色</th>
              <th class="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">智能委派</th>
              <th class="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">接入</th>
              <th class="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200 bg-white dark:divide-gray-800 dark:bg-gray-900">
            <tr v-for="app in filteredApps" :key="app.id" class="group hover:bg-gray-50/80 dark:hover:bg-gray-800/60">
              <td class="px-5 py-4">
                <div class="flex items-start gap-3">
                  <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/40 dark:text-blue-300">
                    <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5a2 2 0 012-2h12a2 2 0 012 2v14l-4-2-4 2-4-2-4 2V5z" />
                    </svg>
                  </div>
                  <div class="min-w-0">
                    <div class="flex flex-wrap items-center gap-1.5">
                      <span class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ app.name }}</span>
                      <span
                        class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                        :class="app.is_active ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-gray-100 text-gray-500'"
                      >{{ app.is_active ? '启用' : '停用' }}</span>
                    </div>
                    <p class="mt-0.5 max-w-xs truncate text-xs text-gray-500" :title="app.description || ''">
                      {{ app.description || '无描述' }}
                    </p>
                    <button
                      type="button"
                      class="mt-1.5 inline-flex items-center gap-1 rounded-md bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
                      title="复制应用 Key"
                      @click="copyAppKey(app.app_key)"
                    >
                      {{ app.app_key }}
                      <ClipboardDocumentIcon class="h-3.5 w-3.5 text-gray-400" />
                    </button>
                  </div>
                </div>
              </td>
              <td class="px-5 py-4 text-sm text-gray-700 dark:text-gray-300">
                {{ app.role_name || (app.role_id ? `角色 #${app.role_id}` : '未关联角色') }}
              </td>
              <td class="px-5 py-4">
                <div v-if="hostLabel(app)" class="min-w-0">
                  <p class="truncate text-sm font-medium text-gray-900 dark:text-gray-100">{{ hostLabel(app) }}</p>
                  <p class="mt-0.5 text-xs text-gray-400">{{ app.lock_entry_agent ? '已锁定入口' : '可切换智能体' }}</p>
                </div>
                <span v-else class="text-sm text-gray-400">未启用</span>
              </td>
              <td class="px-5 py-4">
                <div class="flex flex-wrap gap-1">
                  <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {{ permissionLabel(app) }}
                  </span>
                  <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {{ originLabel(app) }}
                  </span>
                  <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {{ app.require_identity ? '必须身份' : '允许代客' }}
                  </span>
                </div>
              </td>
              <td class="px-5 py-4">
                <div class="flex items-center justify-end gap-1">
                  <button
                    type="button"
                    class="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:text-gray-300 disabled:hover:bg-transparent"
                    :disabled="!app.is_active || debuggingKey === app.app_key"
                    :title="app.is_active ? '用业务系统同样的 iframe 调试该应用' : '应用已停用'"
                    @click="openEmbedDebug(app)"
                  >
                    <PlayIcon class="h-4 w-4" />
                    {{ debuggingKey === app.app_key ? '签发中…' : '对话调试' }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-primary hover:bg-primary/10"
                    @click="openPromptModal(app)"
                  >
                    <ChatBubbleLeftRightIcon class="h-4 w-4" />
                    提示词 {{ app.shortcut_prompts?.length || 0 }}
                  </button>
                  <button
                    v-if="canEdit"
                    type="button"
                    class="rounded-lg p-1.5 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/40"
                    title="编辑"
                    @click="openModal(app)"
                  >
                    <PencilSquareIcon class="h-4 w-4" />
                  </button>
                  <button
                    v-if="canDelete"
                    type="button"
                    class="rounded-lg p-1.5 text-gray-400 opacity-0 transition-all hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 focus:opacity-100 dark:hover:bg-red-950/40"
                    title="删除"
                    @click="deletingApp = app; showDeleteConfirm = true"
                  >
                    <TrashIcon class="h-4 w-4" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else class="space-y-3">
        <article
          v-for="app in filteredApps"
          :key="app.id"
          class="rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-1.5">
                <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ app.name }}</h2>
                <span
                  class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                  :class="app.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'"
                >{{ app.is_active ? '启用' : '停用' }}</span>
              </div>
              <p class="mt-1 text-xs text-gray-500">{{ app.description || '无描述' }}</p>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <button v-if="canEdit" type="button" class="rounded-lg p-1.5 text-blue-600 hover:bg-blue-50" @click="openModal(app)">
                <PencilSquareIcon class="h-4 w-4" />
              </button>
              <button
                v-if="canDelete"
                type="button"
                class="rounded-lg p-1.5 text-red-500 hover:bg-red-50"
                @click="deletingApp = app; showDeleteConfirm = true"
              >
                <TrashIcon class="h-4 w-4" />
              </button>
            </div>
          </div>
          <button
            type="button"
            class="mt-2 inline-flex items-center gap-1 rounded-md bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-600"
            @click="copyAppKey(app.app_key)"
          >
            {{ app.app_key }}
            <ClipboardDocumentIcon class="h-3.5 w-3.5 text-gray-400" />
          </button>
          <dl class="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div class="rounded-lg bg-slate-50 px-2.5 py-2 dark:bg-gray-800">
              <dt class="text-[11px] text-gray-400">角色</dt>
              <dd class="mt-0.5 font-medium text-gray-800 dark:text-gray-200">{{ app.role_name || '未关联' }}</dd>
            </div>
            <div class="rounded-lg bg-slate-50 px-2.5 py-2 dark:bg-gray-800">
              <dt class="text-[11px] text-gray-400">智能委派</dt>
              <dd class="mt-0.5 font-medium text-gray-800 dark:text-gray-200">{{ hostLabel(app) || '未启用' }}</dd>
            </div>
          </dl>
          <div class="mt-3 flex items-center justify-between gap-2">
            <div class="flex flex-wrap gap-1">
              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{{ permissionLabel(app) }}</span>
              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{{ originLabel(app) }}</span>
            </div>
            <div class="flex shrink-0 items-center gap-3">
              <button
                type="button"
                class="inline-flex items-center gap-1 text-xs text-primary disabled:cursor-not-allowed disabled:text-gray-300"
                :disabled="!app.is_active || debuggingKey === app.app_key"
                @click="openEmbedDebug(app)"
              >
                <PlayIcon class="h-4 w-4" />
                {{ debuggingKey === app.app_key ? '签发中…' : '对话调试' }}
              </button>
              <button type="button" class="inline-flex items-center gap-1 text-xs text-primary" @click="openPromptModal(app)">
                <ChatBubbleLeftRightIcon class="h-4 w-4" />
                提示词 {{ app.shortcut_prompts?.length || 0 }}
              </button>
            </div>
          </div>
        </article>
      </div>
    </div>

    <div v-if="showModal" class="fixed inset-0 z-[9990] flex items-end justify-center p-0 sm:items-center sm:p-4">
      <div class="absolute inset-0 bg-black/45 backdrop-blur-[2px]" @click="showModal = false"></div>
      <div
        class="relative flex w-full max-w-2xl flex-col overflow-hidden bg-white shadow-2xl dark:bg-gray-900"
        :class="isMobile ? 'h-[92vh] rounded-t-2xl' : 'max-h-[90vh] rounded-2xl'"
      >
        <div class="flex shrink-0 items-center justify-between gap-3 border-b border-gray-100 bg-gray-50/80 px-6 py-4 dark:border-gray-800 dark:bg-gray-950/60">
          <h2 class="text-lg font-semibold text-gray-900 dark:text-gray-100">{{ isEditing ? '编辑嵌入应用' : '登记嵌入应用' }}</h2>
          <button type="button" class="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-200/80 hover:text-gray-700" @click="showModal = false">
            <XMarkIcon class="h-5 w-5" />
          </button>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div class="space-y-6">
            <section>
              <h3 :class="sectionTitleClass">
                <span class="h-3.5 w-1 rounded-full bg-primary"></span>
                基本信息
              </h3>
              <div class="grid gap-x-4 gap-y-4 sm:grid-cols-2">
                <label>
                  <span :class="labelClass">名称</span>
                  <input v-model="form.name" :class="inputClass" placeholder="如 CRM 门户" />
                </label>
                <div>
                  <span :class="labelClass">
                    应用 Key
                    <button type="button" :class="hintBtnClass" :aria-label="FIELD_HINTS.appKey" @click="toggleHint('appKey', $event)">
                      <QuestionMarkCircleIcon class="h-3.5 w-3.5" />
                    </button>
                  </span>
                  <div
                    v-if="!isEditing"
                    class="flex h-10 items-center rounded-xl border border-dashed border-gray-200 bg-gray-50 px-3 text-sm text-gray-400 dark:border-gray-700 dark:bg-gray-950"
                  >保存后自动生成</div>
                  <div v-else class="relative">
                    <input :value="form.app_key" disabled :class="inputClass" class="font-mono text-[13px] !pr-10" />
                    <button
                      type="button"
                      class="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-white hover:text-primary dark:hover:bg-gray-800"
                      title="复制"
                      @click="copyAppKey(form.app_key)"
                    >
                      <ClipboardDocumentIcon class="h-4 w-4" />
                    </button>
                  </div>
                </div>
                <label>
                  <span :class="labelClass">描述</span>
                  <input v-model="form.description" :class="inputClass" placeholder="给同事看的用途说明" />
                </label>
                <div>
                  <span :class="labelClass">
                    启用
                    <button type="button" :class="hintBtnClass" :aria-label="FIELD_HINTS.active" @click="toggleHint('active', $event)">
                      <QuestionMarkCircleIcon class="h-3.5 w-3.5" />
                    </button>
                  </span>
                  <div class="flex h-10 items-center">
                    <Switch v-model="form.is_active" />
                  </div>
                </div>
              </div>
            </section>

            <section>
              <h3 :class="sectionTitleClass">
                <span class="h-3.5 w-1 rounded-full bg-primary"></span>
                对话入口
              </h3>
              <div class="grid gap-x-4 gap-y-4 sm:grid-cols-2">
                <div class="relative" @click.stop>
                  <span :class="labelClass">
                    关联角色
                    <button type="button" :class="hintBtnClass" :aria-label="FIELD_HINTS.role" @click="toggleHint('role', $event)">
                      <QuestionMarkCircleIcon class="h-3.5 w-3.5" />
                    </button>
                  </span>
                  <button type="button" :class="selectButtonClass" @click="toggleMenu('role', $event)">
                    <span class="truncate" :class="selectedRole ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400'">
                      {{ selectedRole ? `${selectedRole.name}（${selectedRole.code}）` : '请选择角色' }}
                    </span>
                    <ChevronDownIcon class="h-4 w-4 shrink-0 text-gray-400" />
                  </button>
                </div>

                <div class="relative" @click.stop>
                  <span :class="labelClass">
                    智能委派宿主
                    <button type="button" :class="hintBtnClass" :aria-label="FIELD_HINTS.host" @click="toggleHint('host', $event)">
                      <QuestionMarkCircleIcon class="h-3.5 w-3.5" />
                    </button>
                  </span>
                  <button
                    type="button"
                    :class="selectButtonClass"
                    :disabled="!roleAgents.length && !form.role_id"
                    @click="toggleMenu('host', $event)"
                  >
                    <span class="truncate" :class="selectedHost ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400'">
                      {{ selectedHost ? (selectedHost.display_name || selectedHost.name) : '未指定（不启用智能委派）' }}
                    </span>
                    <ChevronDownIcon class="h-4 w-4 shrink-0 text-gray-400" />
                  </button>
                </div>

                <div>
                  <span :class="labelClass">
                    锁定入口智能体
                    <button type="button" :class="hintBtnClass" :aria-label="FIELD_HINTS.lock" @click="toggleHint('lock', $event)">
                      <QuestionMarkCircleIcon class="h-3.5 w-3.5" />
                    </button>
                  </span>
                  <div class="flex h-10 items-center">
                    <Switch v-model="form.lock_entry_agent" />
                  </div>
                </div>
                <div>
                  <span :class="labelClass">
                    必须提交业务用户身份
                    <button type="button" :class="hintBtnClass" :aria-label="FIELD_HINTS.identity" @click="toggleHint('identity', $event)">
                      <QuestionMarkCircleIcon class="h-3.5 w-3.5" />
                    </button>
                  </span>
                  <div class="flex h-10 items-center">
                    <Switch v-model="form.require_identity" />
                  </div>
                </div>
              </div>
            </section>

            <section>
              <h3 :class="sectionTitleClass">
                <span class="h-3.5 w-1 rounded-full bg-primary"></span>
                对话设置
              </h3>
              <p class="mb-3 text-xs leading-5 text-gray-400">同一嵌入应用内所有用户共用，不按个人保存。智能委派仍在上方「对话入口」里配置。</p>
              <div class="grid gap-x-4 gap-y-4 sm:grid-cols-2">
                <div>
                  <span :class="labelClass">主题模式</span>
                  <div class="flex h-10 items-center rounded-xl bg-gray-100 p-1 dark:bg-gray-800">
                    <button
                      type="button"
                      class="flex-1 rounded-lg py-1.5 text-xs font-medium transition-all"
                      :class="form.chat_settings.theme === 'light' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'"
                      @click="form.chat_settings.theme = 'light'"
                    >浅色</button>
                    <button
                      type="button"
                      class="flex-1 rounded-lg py-1.5 text-xs font-medium transition-all"
                      :class="form.chat_settings.theme === 'dark' ? 'bg-gray-700 text-white shadow-sm' : 'text-gray-500'"
                      @click="form.chat_settings.theme = 'dark'"
                    >深色</button>
                  </div>
                </div>
                <div>
                  <span :class="labelClass">AI 消息排版</span>
                  <select v-model="form.chat_settings.markdown_theme" :class="inputClass">
                    <option v-for="item in EMBED_MARKDOWN_THEMES" :key="item.id" :value="item.id">{{ item.label }}</option>
                  </select>
                </div>
                <div class="sm:col-span-2">
                  <span :class="labelClass">主题颜色</span>
                  <div class="flex flex-wrap items-center gap-2">
                    <button
                      v-for="color in EMBED_THEME_COLORS"
                      :key="color"
                      type="button"
                      class="flex h-7 w-7 items-center justify-center rounded-full transition-transform hover:scale-110"
                      :class="form.chat_settings.primary_color === color ? 'ring-2 ring-offset-2 ring-primary' : ''"
                      :style="{ backgroundColor: color }"
                      @click="form.chat_settings.primary_color = color"
                    >
                      <span v-if="form.chat_settings.primary_color === color" class="text-xs font-bold text-white">✓</span>
                    </button>
                    <label class="relative flex h-7 w-7 cursor-pointer items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-red-500 via-green-500 to-blue-500">
                      <input
                        type="color"
                        class="absolute inset-0 cursor-pointer opacity-0"
                        :value="form.chat_settings.primary_color"
                        @input="onPrimaryColorInput"
                      />
                      <span class="pointer-events-none text-xs font-bold text-white">+</span>
                    </label>
                  </div>
                </div>
                <div>
                  <span :class="labelClass">隐藏 AI 消息外框</span>
                  <div class="flex h-10 items-center">
                    <Switch v-model="form.chat_settings.hide_message_border" />
                  </div>
                </div>
                <div>
                  <span :class="labelClass">Bash 运行环境横幅</span>
                  <div class="flex h-10 items-center">
                    <Switch v-model="form.chat_settings.show_bash_banner" />
                  </div>
                </div>
                <div>
                  <span :class="labelClass">多智能体协同</span>
                  <div class="flex h-10 items-center">
                    <Switch v-model="form.chat_settings.enable_multi_agent" />
                  </div>
                </div>
                <div>
                  <span :class="labelClass">SQL PLAN 中间层</span>
                  <div class="flex h-10 items-center">
                    <Switch v-model="form.chat_settings.enable_sql_plan" />
                  </div>
                </div>
                <div>
                  <span :class="labelClass">思考过程默认展开</span>
                  <div class="flex h-10 items-center">
                    <Switch v-model="form.chat_settings.expand_thoughts" />
                  </div>
                </div>
                <div>
                  <span :class="labelClass">反幻觉校验</span>
                  <div class="flex h-10 items-center">
                    <Switch v-model="form.chat_settings.enable_grounding" />
                  </div>
                </div>
                <div v-if="form.chat_settings.enable_grounding">
                  <span :class="labelClass">校验失败后实时输出</span>
                  <div class="flex h-10 items-center">
                    <Switch
                      :model-value="form.chat_settings.grounding_block_mode === 'stream_with_retraction'"
                      @update:model-value="form.chat_settings.grounding_block_mode = $event ? 'stream_with_retraction' : 'strict_buffer'"
                    />
                  </div>
                </div>
              </div>
            </section>

            <section>
              <h3 :class="sectionTitleClass">
                <span class="h-3.5 w-1 rounded-full bg-primary"></span>
                安全与接入
              </h3>
              <div class="grid gap-x-4 gap-y-4 sm:grid-cols-2">
                <div class="relative" @click.stop>
                  <span :class="labelClass">数据权限</span>
                  <button type="button" :class="selectButtonClass" @click="toggleMenu('mode', $event)">
                    <span class="truncate text-gray-900 dark:text-gray-100">{{ selectedPermission.label }}</span>
                    <ChevronDownIcon class="h-4 w-4 shrink-0 text-gray-400" />
                  </button>
                </div>
                <label>
                  <span :class="labelClass">
                    允许的宿主域名
                    <button type="button" :class="hintBtnClass" :aria-label="FIELD_HINTS.origins" @click="toggleHint('origins', $event)">
                      <QuestionMarkCircleIcon class="h-3.5 w-3.5" />
                    </button>
                  </span>
                  <textarea
                    v-model="form.originsText"
                    rows="1"
                    :class="inputClass"
                    class="h-10 min-h-10 resize-y py-2 leading-5"
                    placeholder="https://crm.example.com"
                  />
                </label>
              </div>
            </section>
          </div>
        </div>

        <div class="flex shrink-0 justify-end gap-2 border-t border-gray-100 bg-gray-50/90 px-6 py-3.5 dark:border-gray-800 dark:bg-gray-950/60">
          <button type="button" class="rounded-xl px-4 py-2 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-200/70 dark:text-gray-300" @click="showModal = false">取消</button>
          <button
            type="button"
            class="rounded-xl bg-primary px-5 py-2 text-sm font-semibold text-white shadow-sm shadow-primary/20 transition-colors hover:bg-primary-hover disabled:opacity-60"
            :disabled="saving"
            @click="saveApp"
          >
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div>
      <div
        v-if="openHint"
        class="fixed z-[10050] w-72 rounded-xl bg-slate-800/95 px-3 py-2.5 text-xs leading-5 text-white shadow-2xl ring-1 ring-white/10 backdrop-blur"
        :style="{ top: `${hintPos.top}px`, left: `${hintPos.left}px` }"
        @click.stop
      >{{ FIELD_HINTS[openHint] }}</div>
      <div
        v-if="openMenu"
        :class="menuClass"
        :style="{
          top: `${menuPos.top}px`,
          left: `${menuPos.left}px`,
          width: `${menuPos.width}px`,
          maxHeight: `${menuPos.maxHeight}px`,
          transform: menuPos.openUp ? 'translateY(-100%)' : undefined,
        }"
        @click.stop
      >
        <template v-if="openMenu === 'role'">
          <button
            v-for="role in roles"
            :key="role.id"
            type="button"
            :class="[menuItemClass, Number(form.role_id) === Number(role.id) ? 'bg-primary/5' : '']"
            @click="form.role_id = role.id; openMenu = ''"
          >
            <span class="min-w-0">
              <span class="block truncate text-sm text-gray-900 dark:text-gray-100">{{ role.name }}</span>
              <span class="block truncate text-xs text-gray-400">{{ role.code }}</span>
            </span>
            <CheckIcon v-if="Number(form.role_id) === Number(role.id)" class="h-4 w-4 shrink-0 text-primary" />
          </button>
        </template>
        <template v-else-if="openMenu === 'host'">
          <button
            type="button"
            :class="[menuItemClass, !form.default_entry_agent_id ? 'bg-primary/5' : '']"
            @click="form.default_entry_agent_id = ''; openMenu = ''"
          >
            <span class="min-w-0">
              <span class="block text-sm text-gray-900 dark:text-gray-100">未指定（不启用智能委派）</span>
              <span class="block text-xs text-gray-400">单个专家直达，多个需手选</span>
            </span>
            <CheckIcon v-if="!form.default_entry_agent_id" class="h-4 w-4 shrink-0 text-primary" />
          </button>
          <button
            v-for="agent in roleAgents"
            :key="agent.id"
            type="button"
            :class="[menuItemClass, form.default_entry_agent_id === agent.id || form.default_entry_agent_id === agent.name ? 'bg-primary/5' : '']"
            @click="form.default_entry_agent_id = agent.id; openMenu = ''"
          >
            <span class="min-w-0">
              <span class="block truncate text-sm text-gray-900 dark:text-gray-100">{{ agent.display_name || agent.name }}</span>
              <span class="block text-xs text-gray-400">{{ isMainRoleAgent(agent) ? '平台主助手' : '可作为替代主助手' }}</span>
            </span>
            <CheckIcon
              v-if="form.default_entry_agent_id === agent.id || form.default_entry_agent_id === agent.name"
              class="h-4 w-4 shrink-0 text-primary"
            />
          </button>
        </template>
        <template v-else-if="openMenu === 'mode'">
          <button
            v-for="option in PERMISSION_OPTIONS"
            :key="option.value"
            type="button"
            :class="[menuItemClass, form.data_permission_mode === option.value ? 'bg-primary/5' : '']"
            @click="form.data_permission_mode = option.value; openMenu = ''"
          >
            <span class="min-w-0">
              <span class="block text-sm text-gray-900 dark:text-gray-100">{{ option.label }}</span>
              <span class="block text-xs text-gray-400">{{ option.hint }}</span>
            </span>
            <CheckIcon v-if="form.data_permission_mode === option.value" class="h-4 w-4 shrink-0 text-primary" />
          </button>
        </template>
      </div>
      </div>
    </Teleport>

    <div v-if="showPromptModal" class="fixed inset-0 z-[9990] flex items-end justify-center p-0 sm:items-center sm:p-4">
      <div class="absolute inset-0 bg-black/45 backdrop-blur-[2px]" @click="showPromptModal = false"></div>
      <div
        class="relative flex h-[70vh] w-full max-w-2xl flex-col overflow-hidden bg-white shadow-2xl dark:bg-gray-900"
        :class="isMobile ? 'rounded-t-2xl' : 'rounded-2xl'"
      >
        <div class="flex shrink-0 items-start justify-between gap-3 border-b border-gray-100 bg-gray-50/80 px-6 py-4 dark:border-gray-800 dark:bg-gray-950/60">
          <div>
            <h2 class="text-lg font-semibold text-gray-900">常用提示词 · {{ promptApp?.name || '' }}</h2>
            <p class="mt-1 text-xs text-gray-400">仅该嵌入应用的 iframe 显示，与站内全局快捷指令、其他子系统互不影响。最多 20 条。</p>
          </div>
          <button type="button" class="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-200/80 hover:text-gray-700" @click="showPromptModal = false">
            <XMarkIcon class="h-5 w-5" />
          </button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div class="space-y-3">
            <div
              v-for="(item, index) in promptDraft"
              :key="index"
              class="rounded-xl border border-gray-100 bg-white p-3 shadow-sm dark:border-gray-800"
            >
              <div class="flex items-center gap-2">
                <input
                  v-model="item.label"
                  :class="inputClass"
                  class="min-w-0 flex-1"
                  placeholder="显示名称，如 对账"
                  maxlength="50"
                  :disabled="!canEdit"
                />
                <button
                  v-if="canEdit"
                  type="button"
                  class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-gray-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/40"
                  title="删除这条提示词"
                  @click="removePromptRow(index)"
                >
                  <TrashIcon class="h-4 w-4" />
                </button>
              </div>
              <textarea
                v-model="item.command"
                rows="4"
                class="mt-2 w-full resize-y rounded-xl border border-gray-200 bg-gray-50/70 px-3 py-2 text-sm leading-6 outline-none transition-all placeholder:text-gray-400 hover:border-gray-300 focus:border-primary focus:bg-white focus:ring-4 focus:ring-primary/10 dark:border-gray-700 dark:bg-gray-950"
                placeholder="发给 AI 的内容，可换行"
                maxlength="500"
                :disabled="!canEdit"
              />
            </div>
          </div>
        </div>
        <div class="flex shrink-0 items-center justify-between border-t border-gray-100 bg-gray-50/90 px-6 py-3.5 dark:border-gray-800 dark:bg-gray-950/60">
          <button
            v-if="canEdit"
            type="button"
            class="text-xs text-primary disabled:text-gray-300"
            :disabled="promptDraft.length >= 20"
            @click="addPromptRow"
          >新增一条</button>
          <span v-else></span>
          <div class="flex gap-2">
            <button type="button" class="rounded-xl px-4 py-2 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-200/70" @click="showPromptModal = false">取消</button>
            <button
              v-if="canEdit"
              type="button"
              class="rounded-xl bg-primary px-5 py-2 text-sm font-semibold text-white shadow-sm shadow-primary/20 hover:bg-primary-hover disabled:opacity-60"
              :disabled="savingPrompts"
              @click="savePrompts"
            >
              {{ savingPrompts ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <Teleport to="body">
    <div
      v-if="debugApp && debugFrameSrc"
      class="fixed inset-0 z-[10060] flex flex-col bg-gray-950"
      @keydown.esc="closeEmbedDebug"
    >
      <div class="flex shrink-0 items-center justify-between gap-3 border-b border-white/10 bg-gray-950 px-4 py-2.5 text-white">
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold">对话调试 · {{ debugApp.name }}</p>
          <p class="truncate text-[11px] text-white/55">与业务系统相同：iframe 加载 /embed/chat?ticket=…</p>
        </div>
        <button
          type="button"
          class="inline-flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-white/80 hover:bg-white/10 hover:text-white"
          @click="closeEmbedDebug"
        >
          <XMarkIcon class="h-4 w-4" />
          关闭
        </button>
      </div>
      <iframe
        class="min-h-0 w-full flex-1 border-0 bg-white"
        :src="debugFrameSrc"
        :title="`对话调试 ${debugApp.name}`"
        allow="clipboard-read; clipboard-write"
      ></iframe>
    </div>
    </Teleport>

    <ConfirmModal
      v-if="showDeleteConfirm"
      title="删除嵌入应用"
      :message="`确定删除「${deletingApp?.name || ''}」？已签发且未兑换的 Ticket 不受影响，新签发将无法再引用该应用 Key。`"
      confirm-text="删除"
      @confirm="confirmDelete"
      @cancel="showDeleteConfirm = false"
    />
  </div>
</template>
