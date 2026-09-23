<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  BoltIcon,
  ChatBubbleLeftRightIcon,
  ChevronDownIcon,
  ClipboardDocumentIcon,
  MagnifyingGlassIcon,
  PaperClipIcon,
  PencilSquareIcon,
  PlayIcon,
  PlusIcon,
  PuzzlePieceIcon,
  Squares2X2Icon,
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
import { packShortcutSkill, splitShortcutSkill, type ShortcutSkillRef } from '../utils/shortcutSkill'

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
const showPromptEditor = ref(false)
const editingPromptIndex = ref<number | null>(null)
const promptPendingDelete = ref<number | null>(null)
const showDeletePromptConfirm = ref(false)
const promptApp = ref<SysEmbedApp | null>(null)
type PromptDraftItem = { label: string; command: string; scenario: string; skill: ShortcutSkillRef | null }

const promptDraft = ref<PromptDraftItem[]>([])
const promptForm = ref<PromptDraftItem>({ label: '', command: '', scenario: '', skill: null })
const promptSkills = ref<Array<{ id: string; name?: string; description?: string; enabled?: string }>>([])
const promptSkillsLoading = ref(false)
const promptSkillMenuDismissed = ref(false)
const promptSkillActiveIndex = ref(0)
const promptSkillListRef = ref<HTMLElement | null>(null)
const promptSkillRowRef = ref<HTMLElement | null>(null)
const promptCommandRef = ref<HTMLTextAreaElement | null>(null)
const promptSkillIndent = ref(0)
const promptSkillScrollTop = ref(0)
const savingPrompts = ref(false)
type ExampleAttachment = { url: string; filename: string; size?: number; ext?: string }
type ExampleDraftItem = PromptDraftItem & { attachments: ExampleAttachment[] }
const showExampleModal = ref(false)
const showExampleEditor = ref(false)
const editingExampleIndex = ref<number | null>(null)
const examplePendingDelete = ref<number | null>(null)
const showDeleteExampleConfirm = ref(false)
const exampleApp = ref<SysEmbedApp | null>(null)
const exampleDraft = ref<ExampleDraftItem[]>([])
const exampleForm = ref<ExampleDraftItem>({ label: '', command: '', scenario: '', skill: null, attachments: [] })
const exampleSkillMenuDismissed = ref(false)
const exampleSkillActiveIndex = ref(0)
const exampleSkillListRef = ref<HTMLElement | null>(null)
const exampleSkillRowRef = ref<HTMLElement | null>(null)
const exampleCommandRef = ref<HTMLTextAreaElement | null>(null)
const exampleSkillIndent = ref(0)
const exampleSkillScrollTop = ref(0)
const exampleFileInputRef = ref<HTMLInputElement | null>(null)
const exampleFileDragging = ref(false)
const uploadingExampleFiles = ref(false)
const savingExamples = ref(false)
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

const emptyPromptRow = (): PromptDraftItem => ({ label: '', command: '', scenario: '', skill: null })

const promptSkillQuery = computed(() => {
  const match = promptForm.value.command.match(/(?:^|\s)\/([^\s/]*)$/)
  return match ? String(match[1] || '').toLowerCase() : null
})

const filteredPromptSkills = computed(() => {
  const query = promptSkillQuery.value
  if (query === null) return []
  return promptSkills.value
    .filter((skill) => {
      if (!query) return true
      return [skill.name, skill.id, skill.description].some((value) => String(value || '').toLowerCase().includes(query))
    })
    .slice(0, 8)
})

const loadPromptSkills = async () => {
  if (promptSkills.value.length || promptSkillsLoading.value) return
  promptSkillsLoading.value = true
  try {
    const sourceApp = showExampleEditor.value ? exampleApp.value : promptApp.value
    const agentId = String(sourceApp?.default_entry_agent_id || '').trim()
    const response = await axios.get('/api/portal/skills', agentId ? { params: { agent_id: agentId } } : undefined)
    promptSkills.value = response.data?.status === 'success'
      ? (response.data.data || []).filter((skill: { enabled?: string }) => skill.enabled !== 'false')
      : []
  } catch (error) {
    console.warn('Failed to load prompt skills', error)
    promptSkills.value = []
  } finally {
    promptSkillsLoading.value = false
  }
}

const syncPromptSkillIndent = () => {
  const width = promptSkillRowRef.value?.offsetWidth || 0
  promptSkillIndent.value = width ? width + 6 : 0
}

const syncPromptSkillScroll = () => {
  promptSkillScrollTop.value = promptCommandRef.value?.scrollTop || 0
}

const pickPromptSkill = (skill: { id: string; name?: string }) => {
  const id = String(skill.id || '').trim()
  if (!id) return
  promptForm.value.skill = { id, name: String(skill.name || id) }
  promptForm.value.command = promptForm.value.command.replace(/(?:^|\s)\/[^\s/]*$/, '').trim()
  nextTick(() => {
    syncPromptSkillIndent()
    promptCommandRef.value?.focus()
  })
}

const scrollActivePromptSkillIntoView = () => {
  const list = promptSkillListRef.value
  const active = list?.querySelector("[data-active='true']")
  if (!list || !(active instanceof HTMLElement)) return
  const top = active.offsetTop
  const bottom = top + active.offsetHeight
  if (top < list.scrollTop) list.scrollTop = top
  else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight
}

const handlePromptCommandKeydown = (event: KeyboardEvent) => {
  if (event.isComposing || !canEdit) return
  const menuOpen = promptSkillQuery.value !== null && !promptSkillMenuDismissed.value
  const skills = filteredPromptSkills.value
  if (menuOpen && skills.length) {
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      promptSkillActiveIndex.value = (promptSkillActiveIndex.value + step + skills.length) % skills.length
      nextTick(scrollActivePromptSkillIntoView)
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      pickPromptSkill(skills[promptSkillActiveIndex.value] || skills[0])
      return
    }
  }
  if (menuOpen && event.key === 'Escape') {
    event.preventDefault()
    promptSkillMenuDismissed.value = true
    return
  }
  if (!promptForm.value.skill || event.altKey || event.metaKey || event.ctrlKey || event.shiftKey) return
  const target = event.target as HTMLTextAreaElement | null
  const caretAtStart = !!target && target.selectionStart === 0 && target.selectionEnd === 0
  const empty = !promptForm.value.command
  const removeByBackspace = event.key === 'Backspace' && (empty || caretAtStart)
  const removeByDelete = event.key === 'Delete' && empty
  if (removeByBackspace || removeByDelete) {
    event.preventDefault()
    promptForm.value.skill = null
  }
}

watch(promptSkillQuery, () => {
  promptSkillMenuDismissed.value = false
  promptSkillActiveIndex.value = 0
})
watch(() => promptForm.value.skill, () => nextTick(syncPromptSkillIndent))
watch(() => promptForm.value.command, () => nextTick(syncPromptSkillScroll))

const packedPromptCommand = (item: PromptDraftItem) => {
  const text = item.command.trim()
  const packed = packShortcutSkill(text, item.skill)
  if (packed.length <= 500) return packed
  if (!item.skill) return packed.slice(0, 500)
  const marker = packShortcutSkill('', item.skill)
  const room = 500 - marker.length - (text ? 1 : 0)
  if (room <= 0) return marker.slice(0, 500)
  return packShortcutSkill(text.slice(0, room), item.skill)
}

const closePromptModal = () => {
  showPromptModal.value = false
  showPromptEditor.value = false
  promptApp.value = null
}

const openPromptModal = (app: SysEmbedApp) => {
  promptApp.value = app
  promptDraft.value = (app.shortcut_prompts || []).map((item) => {
    const parsed = splitShortcutSkill(String(item.command || ''))
    return {
      label: String(item.label || ''),
      command: parsed.text,
      scenario: String(item.scenario || ''),
      skill: parsed.skill,
    }
  })
  showPromptEditor.value = false
  editingPromptIndex.value = null
  promptSkills.value = []
  showPromptModal.value = true
}

const openPromptEditor = (index: number | null) => {
  if (!canEdit) return
  if (index === null && promptDraft.value.length >= 20) return
  editingPromptIndex.value = index
  const source = index === null ? emptyPromptRow() : promptDraft.value[index]
  promptForm.value = {
    label: source?.label || '',
    command: source?.command || '',
    scenario: source?.scenario || '',
    skill: source?.skill ? { ...source.skill } : null,
  }
  promptSkillMenuDismissed.value = false
  promptSkillActiveIndex.value = 0
  promptSkillScrollTop.value = 0
  promptSkillIndent.value = 0
  showPromptEditor.value = true
  void loadPromptSkills()
  nextTick(syncPromptSkillIndent)
}

const savePrompts = async (next: PromptDraftItem[]) => {
  if (!promptApp.value) return false
  const shortcut_prompts = next
    .map((item) => ({
      label: String(item.label || '').trim(),
      command: packedPromptCommand(item),
      scenario: String(item.scenario || '').trim().slice(0, 200),
    }))
    .filter((item) => item.label && item.command)
  savingPrompts.value = true
  try {
    await embedAppApi.update(promptApp.value.id, { shortcut_prompts })
    promptDraft.value = next.map((item) => ({
      label: item.label,
      command: item.command,
      scenario: item.scenario,
      skill: item.skill ? { ...item.skill } : null,
    }))
    const appId = promptApp.value.id
    apps.value = apps.value.map((app) => (app.id === appId ? { ...app, shortcut_prompts } : app))
    promptApp.value = { ...promptApp.value, shortcut_prompts }
    return true
  } catch (error: any) {
    const detail = error.response?.data?.detail
    const message = Array.isArray(detail)
      ? detail.map((item: any) => item.msg || item).join('; ')
      : (detail || '保存失败')
    showToast(String(message), 'error')
    return false
  } finally {
    savingPrompts.value = false
  }
}

const submitPromptEditor = async () => {
  const label = promptForm.value.label.trim()
  const command = packedPromptCommand(promptForm.value)
  if (!label || !command || savingPrompts.value) return
  const item: PromptDraftItem = {
    label,
    command: promptForm.value.command.trim(),
    scenario: promptForm.value.scenario.trim().slice(0, 200),
    skill: promptForm.value.skill ? { ...promptForm.value.skill } : null,
  }
  const next = promptDraft.value.slice()
  if (editingPromptIndex.value === null) next.push(item)
  else next.splice(editingPromptIndex.value, 1, item)
  const saved = await savePrompts(next)
  if (saved) showPromptEditor.value = false
}

const askDeletePrompt = (index: number) => {
  promptPendingDelete.value = index
  showDeletePromptConfirm.value = true
}

const executeDeletePrompt = async () => {
  const index = promptPendingDelete.value
  if (index === null || savingPrompts.value) return
  const next = promptDraft.value.filter((_, itemIndex) => itemIndex !== index)
  const saved = await savePrompts(next)
  if (!saved) return
  showDeletePromptConfirm.value = false
  promptPendingDelete.value = null
}

const emptyExample = (): ExampleDraftItem => ({ label: '', command: '', scenario: '', skill: null, attachments: [] })

const exampleSkillQuery = computed(() => {
  const match = exampleForm.value.command.match(/(?:^|\s)\/([^\s/]*)$/)
  return match ? String(match[1] || '').toLowerCase() : null
})

const filteredExampleSkills = computed(() => {
  const query = exampleSkillQuery.value
  if (query === null) return []
  return promptSkills.value
    .filter((skill) => {
      if (!query) return true
      return [skill.name, skill.id, skill.description].some((value) => String(value || '').toLowerCase().includes(query))
    })
    .slice(0, 8)
})

const syncExampleSkillIndent = () => {
  const width = exampleSkillRowRef.value?.offsetWidth || 0
  exampleSkillIndent.value = width ? width + 6 : 0
}

const syncExampleSkillScroll = () => {
  exampleSkillScrollTop.value = exampleCommandRef.value?.scrollTop || 0
}

const pickExampleSkill = (skill: { id: string; name?: string }) => {
  const id = String(skill.id || '').trim()
  if (!id) return
  exampleForm.value.skill = { id, name: String(skill.name || id) }
  exampleForm.value.command = exampleForm.value.command.replace(/(?:^|\s)\/[^\s/]*$/, '').trim()
  nextTick(() => {
    syncExampleSkillIndent()
    exampleCommandRef.value?.focus()
  })
}

const handleExampleCommandKeydown = (event: KeyboardEvent) => {
  if (event.isComposing || !canEdit) return
  const menuOpen = exampleSkillQuery.value !== null && !exampleSkillMenuDismissed.value
  const skills = filteredExampleSkills.value
  if (menuOpen && skills.length) {
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      exampleSkillActiveIndex.value = (exampleSkillActiveIndex.value + step + skills.length) % skills.length
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      pickExampleSkill(skills[exampleSkillActiveIndex.value] || skills[0])
      return
    }
  }
  if (menuOpen && event.key === 'Escape') {
    event.preventDefault()
    exampleSkillMenuDismissed.value = true
    return
  }
  if (!exampleForm.value.skill || event.altKey || event.metaKey || event.ctrlKey || event.shiftKey) return
  const target = event.target as HTMLTextAreaElement | null
  const caretAtStart = !!target && target.selectionStart === 0 && target.selectionEnd === 0
  const empty = !exampleForm.value.command
  if ((event.key === 'Backspace' && (empty || caretAtStart)) || (event.key === 'Delete' && empty)) {
    event.preventDefault()
    exampleForm.value.skill = null
  }
}

watch(exampleSkillQuery, () => {
  exampleSkillMenuDismissed.value = false
  exampleSkillActiveIndex.value = 0
})
watch(() => exampleForm.value.skill, () => nextTick(syncExampleSkillIndent))
watch(() => exampleForm.value.command, () => nextTick(syncExampleSkillScroll))

const closeExampleModal = () => {
  showExampleModal.value = false
  showExampleEditor.value = false
  exampleApp.value = null
}

const openExampleModal = (app: SysEmbedApp) => {
  exampleApp.value = app
  exampleDraft.value = (app.examples || []).map((item) => {
    const parsed = splitShortcutSkill(String(item.command || ''))
    return {
      label: String(item.label || ''),
      command: parsed.text,
      scenario: String(item.scenario || ''),
      skill: parsed.skill,
      attachments: Array.isArray(item.attachments) ? item.attachments.map((file) => ({ ...file })) : [],
    }
  })
  showExampleEditor.value = false
  editingExampleIndex.value = null
  promptSkills.value = []
  showExampleModal.value = true
}

const openExampleEditor = (index: number | null) => {
  if (!canEdit) return
  if (index === null && exampleDraft.value.length >= 20) return
  editingExampleIndex.value = index
  const source = index === null ? emptyExample() : exampleDraft.value[index]
  exampleForm.value = {
    label: source?.label || '',
    command: source?.command || '',
    scenario: source?.scenario || '',
    skill: source?.skill ? { ...source.skill } : null,
    attachments: (source?.attachments || []).map((file) => ({ ...file })),
  }
  exampleSkillMenuDismissed.value = false
  exampleSkillActiveIndex.value = 0
  exampleSkillScrollTop.value = 0
  exampleSkillIndent.value = 0
  showExampleEditor.value = true
  void loadPromptSkills()
  nextTick(syncExampleSkillIndent)
}

const uploadExampleFiles = async (files: File[]) => {
  if (!exampleApp.value || !files.length) return
  uploadingExampleFiles.value = true
  try {
    for (const file of files) {
      if (exampleForm.value.attachments.length >= 10) {
        showToast('一条示例最多 10 个附件', 'warning')
        break
      }
      const form = new FormData()
      form.append('file', file)
      const res = await axios.post(`/api/portal/embed-apps/${exampleApp.value.id}/example-files`, form)
      const data = res.data?.data
      if (!data?.url || !data?.filename) throw new Error('上传失败')
      exampleForm.value.attachments.push({
        url: String(data.url),
        filename: String(data.filename),
        size: Number(data.size || file.size || 0),
        ext: String(data.ext || ''),
      })
    }
  } catch (error: any) {
    showToast(error.response?.data?.detail || error.message || '上传附件失败', 'error')
  } finally {
    uploadingExampleFiles.value = false
  }
}

const onExampleFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  input.value = ''
  await uploadExampleFiles(files)
}

const onExampleDragLeave = (event: DragEvent) => {
  const next = event.relatedTarget
  const current = event.currentTarget
  if (current instanceof HTMLElement && next instanceof Node && current.contains(next)) return
  exampleFileDragging.value = false
}

const onExampleFileDrop = async (event: DragEvent) => {
  exampleFileDragging.value = false
  if (!canEdit || uploadingExampleFiles.value) return
  await uploadExampleFiles(Array.from(event.dataTransfer?.files || []))
}

const removeExampleAttachment = (index: number) => {
  exampleForm.value.attachments.splice(index, 1)
}

const saveExamples = async (next: ExampleDraftItem[]) => {
  if (!exampleApp.value) return false
  const examples = next
    .map((item) => ({
      label: String(item.label || '').trim(),
      command: packedPromptCommand(item),
      scenario: String(item.scenario || '').trim().slice(0, 200),
      attachments: (item.attachments || []).slice(0, 10),
    }))
    .filter((item) => item.label && (item.command || item.attachments.length))
  savingExamples.value = true
  try {
    await embedAppApi.update(exampleApp.value.id, { examples })
    exampleDraft.value = next.map((item) => ({
      ...item,
      skill: item.skill ? { ...item.skill } : null,
      attachments: item.attachments.map((file) => ({ ...file })),
    }))
    const appId = exampleApp.value.id
    apps.value = apps.value.map((app) => (app.id === appId ? { ...app, examples } : app))
    exampleApp.value = { ...exampleApp.value, examples }
    return true
  } catch (error: any) {
    const detail = error.response?.data?.detail
    const message = Array.isArray(detail)
      ? detail.map((item: any) => item.msg || item).join('; ')
      : (detail || '保存失败')
    showToast(String(message), 'error')
    return false
  } finally {
    savingExamples.value = false
  }
}

const submitExampleEditor = async () => {
  const label = exampleForm.value.label.trim()
  const command = packedPromptCommand(exampleForm.value)
  if (!label || (!command && !exampleForm.value.attachments.length) || savingExamples.value) return
  const item: ExampleDraftItem = {
    label,
    command: exampleForm.value.command.trim(),
    scenario: exampleForm.value.scenario.trim().slice(0, 200),
    skill: exampleForm.value.skill ? { ...exampleForm.value.skill } : null,
    attachments: exampleForm.value.attachments.map((file) => ({ ...file })),
  }
  const next = exampleDraft.value.slice()
  if (editingExampleIndex.value === null) next.push(item)
  else next.splice(editingExampleIndex.value, 1, item)
  const saved = await saveExamples(next)
  if (saved) showExampleEditor.value = false
}

const askDeleteExample = (index: number) => {
  examplePendingDelete.value = index
  showDeleteExampleConfirm.value = true
}

const executeDeleteExample = async () => {
  const index = examplePendingDelete.value
  if (index === null || savingExamples.value) return
  const next = exampleDraft.value.filter((_, itemIndex) => itemIndex !== index)
  const saved = await saveExamples(next)
  if (!saved) return
  showDeleteExampleConfirm.value = false
  examplePendingDelete.value = null
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
                    @click="openExampleModal(app)"
                  >
                    <Squares2X2Icon class="h-4 w-4" />
                    示例库 {{ app.examples?.length || 0 }}
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
              <button type="button" class="inline-flex items-center gap-1 text-xs text-primary" @click="openExampleModal(app)">
                <Squares2X2Icon class="h-4 w-4" />
                示例库 {{ app.examples?.length || 0 }}
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
                  <span :class="labelClass">Bash 运行环境提醒</span>
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

    <Teleport to="body">
      <div v-if="showPromptModal" class="fixed inset-0 z-[1400] overflow-hidden">
        <div class="absolute inset-0 bg-gray-900/30" @click="closePromptModal"></div>
        <div
          class="absolute inset-y-0 right-0 flex h-full w-full max-w-md flex-col border-l border-gray-200 bg-white shadow-2xl animate-slide-in-right dark:border-gray-700 dark:bg-gray-900"
          role="dialog"
          aria-label="常用提示词"
          @click.stop
        >
          <div class="flex shrink-0 items-center justify-between gap-3 border-b border-gray-100 px-4 py-3 dark:border-gray-700">
            <div class="flex min-w-0 items-center gap-2">
              <ChatBubbleLeftRightIcon class="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              <h3 class="truncate text-sm font-black text-gray-800 dark:text-gray-100">常用提示词 · {{ promptApp?.name || '' }}</h3>
            </div>
            <button
              type="button"
              class="inline-flex h-8 w-8 items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800"
              aria-label="关闭"
              @click="closePromptModal"
            >
              <XMarkIcon class="h-4 w-4" />
            </button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            <div v-if="!promptDraft.length" class="px-4 py-12 text-center text-sm text-gray-400">还没有快捷指令</div>
            <div
              v-for="(item, index) in promptDraft"
              :key="index"
              class="group flex items-center gap-1 border-t border-gray-100 px-3 py-1.5 first:border-t-0 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/60"
            >
              <div class="flex min-w-0 flex-1 items-center gap-2 py-1.5">
                <ChatBubbleLeftRightIcon class="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-sm font-medium text-gray-800 dark:text-gray-100">{{ item.label }}</span>
                  <span v-if="item.scenario" class="block truncate text-xs text-gray-400">{{ item.scenario }}</span>
                </span>
              </div>
              <button
                v-if="canEdit"
                type="button"
                class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-primary dark:hover:bg-gray-800"
                title="编辑这条指令"
                aria-label="编辑"
                @click="openPromptEditor(index)"
              >
                <PencilSquareIcon class="h-4 w-4" />
              </button>
              <button
                v-if="canEdit"
                type="button"
                class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-red-500 dark:hover:bg-gray-800"
                title="删除这条指令"
                aria-label="删除"
                @click="askDeletePrompt(index)"
              >
                <TrashIcon class="h-4 w-4" />
              </button>
            </div>
          </div>
          <div v-if="canEdit" class="shrink-0 border-t border-gray-100 p-3 dark:border-gray-700">
            <button
              type="button"
              class="flex w-full items-center justify-center gap-1.5 rounded-xl px-3 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
              :style="{ backgroundColor: 'var(--primary-color, #1677ff)' }"
              :disabled="promptDraft.length >= 20 || savingPrompts"
              @click="openPromptEditor(null)"
            >
              添加指令
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div
        v-if="showPromptEditor"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/20 p-4 backdrop-blur-sm"
        @click.self="showPromptEditor = false"
      >
        <div class="flex h-[min(30rem,64vh)] w-full max-w-[48rem] flex-col overflow-visible rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800">
          <div class="flex items-center justify-between rounded-t-xl border-b border-gray-100 bg-gray-50 px-6 py-4 dark:border-gray-700 dark:bg-gray-800/50">
            <h3 class="text-base font-bold text-gray-800 dark:text-gray-200">{{ editingPromptIndex === null ? '新建快捷指令' : '编辑快捷指令' }}</h3>
            <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="showPromptEditor = false">
              <XMarkIcon class="h-4 w-4" />
            </button>
          </div>
          <div class="flex min-h-0 flex-1 flex-col space-y-4 p-6">
            <div>
              <label class="mb-1 block text-[10px] font-bold uppercase text-gray-400">显示名称</label>
              <input v-model="promptForm.label" type="text" maxlength="50" placeholder="如：🏢 查机房" class="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-3 text-sm outline-none transition-all focus:ring-1 focus:ring-primary dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100" />
            </div>
            <div>
              <label class="mb-1 block text-[10px] font-bold uppercase text-gray-400">使用场景</label>
              <input v-model="promptForm.scenario" type="text" maxlength="200" placeholder="说明这条指令做什么，例如：把附件里的问题整理成企业整改任务" class="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-3 text-sm outline-none transition-all focus:ring-1 focus:ring-primary dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100" />
            </div>
            <div class="flex min-h-0 flex-1 flex-col">
              <label class="mb-1 block text-[10px] font-bold uppercase text-gray-400">指令内容</label>
              <div class="relative flex min-h-0 flex-1 flex-col">
                <div
                  v-if="promptSkillQuery !== null && !promptSkillMenuDismissed"
                  class="absolute bottom-full left-0 right-0 z-20 mb-2 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800"
                >
                  <div class="flex items-center gap-1 border-b border-gray-200 px-2.5 dark:border-gray-700">
                    <span class="mb-2 h-3.5 w-1 shrink-0 rounded-full bg-primary" />
                    <span class="relative px-2 pb-2 pt-2 text-xs font-semibold text-gray-900 dark:text-gray-100">
                      技能
                      <span class="ml-1 rounded-md bg-primary/10 px-1.5 py-0.5 text-[9px] font-bold text-primary">{{ filteredPromptSkills.length }}</span>
                      <span class="absolute inset-x-2 bottom-0 h-0.5 rounded-t-full bg-primary" />
                    </span>
                  </div>
                  <div ref="promptSkillListRef" class="max-h-48 overflow-y-auto px-1.5 py-1.5">
                    <div v-if="promptSkillsLoading" class="flex h-16 items-center justify-center text-[11px] text-gray-400">正在加载技能…</div>
                    <div v-else-if="!filteredPromptSkills.length" class="flex h-16 items-center justify-center text-[11px] text-gray-400">暂无匹配技能</div>
                    <button
                      v-for="(skill, skillIndex) in filteredPromptSkills"
                      :key="skill.id"
                      type="button"
                      class="flex h-12 w-full items-center gap-2 rounded-lg px-2 text-left"
                      :class="skillIndex === promptSkillActiveIndex
                        ? 'bg-amber-50 ring-1 ring-amber-200/70 dark:bg-amber-950/40 dark:ring-amber-800/60'
                        : 'hover:bg-amber-50 dark:hover:bg-amber-950/40'"
                      :data-active="skillIndex === promptSkillActiveIndex ? 'true' : undefined"
                      @mouseenter="promptSkillActiveIndex = skillIndex"
                      @mousedown.prevent
                      @click="pickPromptSkill(skill)"
                    >
                      <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-amber-100 bg-amber-50 text-amber-600 dark:border-amber-800/60 dark:bg-amber-950/40 dark:text-amber-300">
                        <PuzzlePieceIcon class="h-3.5 w-3.5" aria-hidden="true" />
                      </span>
                      <span class="min-w-0 flex-1">
                        <span class="flex items-center gap-1.5">
                          <span class="truncate text-[12px] font-medium leading-5 text-gray-800 dark:text-gray-100">{{ skill.name || skill.id }}</span>
                          <span class="shrink-0 rounded border border-amber-100 bg-amber-50 px-1 py-0.5 text-[8px] font-bold text-amber-700 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-300">平台技能</span>
                        </span>
                        <span class="block truncate font-mono text-[10px] leading-4 text-gray-400 opacity-70">{{ skill.description || skill.id }}</span>
                      </span>
                    </button>
                  </div>
                </div>
                <div class="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 focus-within:ring-1 focus-within:ring-primary dark:border-gray-700 dark:bg-gray-900">
                  <div v-if="promptForm.skill" ref="promptSkillRowRef" class="absolute left-3 top-3 z-20 flex h-5 items-center" :style="{ transform: `translateY(-${promptSkillScrollTop}px)` }">
                    <span class="group/skill inline-flex h-5 max-w-full items-center rounded-full bg-gray-100 px-2 text-sm leading-none text-gray-700 dark:bg-gray-700 dark:text-gray-100">
                      <span class="relative mr-1 inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center text-gray-500">
                        <BoltIcon class="h-3.5 w-3.5 group-hover/skill:opacity-0" aria-hidden="true" />
                        <button
                          type="button"
                          class="absolute inset-0 hidden items-center justify-center rounded-full text-gray-500 hover:bg-gray-200 hover:text-gray-800 group-hover/skill:flex dark:hover:bg-gray-600"
                          aria-label="移除技能"
                          @mousedown.prevent
                          @click.stop="promptForm.skill = null"
                        >
                          <XMarkIcon class="h-3 w-3" />
                        </button>
                      </span>
                      <span class="truncate">{{ promptForm.skill.name }}</span>
                    </span>
                  </div>
                  <textarea
                    ref="promptCommandRef"
                    v-model="promptForm.command"
                    placeholder="输入要发送给 AI 的文字，输入 / 选择技能"
                    class="min-h-0 w-full flex-1 resize-none bg-transparent py-1 text-sm leading-6 text-gray-900 outline-none dark:text-gray-100"
                    :style="promptSkillIndent ? { textIndent: `${promptSkillIndent}px` } : undefined"
                    @scroll="syncPromptSkillScroll"
                    @keydown="handlePromptCommandKeydown"
                  />
                </div>
              </div>
            </div>
            <button
              type="button"
              class="w-full shrink-0 rounded-lg bg-primary py-3 text-sm font-bold text-white shadow-md shadow-primary/20 transition-all hover:opacity-90 disabled:opacity-50"
              :style="{ backgroundColor: 'var(--primary-color, #1677ff)' }"
              :disabled="savingPrompts || !promptForm.label.trim() || (!promptForm.command.trim() && !promptForm.skill)"
              @click="submitPromptEditor"
            >
              {{ savingPrompts ? '保存中…' : (editingPromptIndex === null ? '添加指令' : '保存修改') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="showExampleModal" class="fixed inset-0 z-[1400] overflow-hidden">
        <div class="absolute inset-0 bg-gray-900/30" @click="closeExampleModal"></div>
        <div
          class="absolute inset-y-0 right-0 flex h-full w-full max-w-md flex-col border-l border-gray-200 bg-white shadow-2xl animate-slide-in-right dark:border-gray-700 dark:bg-gray-900"
          role="dialog"
          aria-label="示例库"
          @click.stop
        >
          <div class="flex shrink-0 items-center justify-between gap-3 border-b border-gray-100 px-4 py-3 dark:border-gray-700">
            <div class="flex min-w-0 items-center gap-2">
              <Squares2X2Icon class="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              <h3 class="truncate text-sm font-black text-gray-800 dark:text-gray-100">示例库 · {{ exampleApp?.name || '' }}</h3>
            </div>
            <button
              type="button"
              class="inline-flex h-8 w-8 items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800"
              aria-label="关闭"
              @click="closeExampleModal"
            >
              <XMarkIcon class="h-4 w-4" />
            </button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            <div v-if="!exampleDraft.length" class="px-4 py-12 text-center text-sm text-gray-400">还没有示例</div>
            <div
              v-for="(item, index) in exampleDraft"
              :key="index"
              class="group flex items-center gap-1 border-t border-gray-100 px-3 py-1.5 first:border-t-0 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/60"
            >
              <div class="flex min-w-0 flex-1 items-center gap-2 py-1.5">
                <Squares2X2Icon class="h-4 w-4 shrink-0 text-gray-400" aria-hidden="true" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-sm font-medium text-gray-800 dark:text-gray-100">{{ item.label }}</span>
                  <span v-if="item.scenario" class="block truncate text-xs text-gray-400">{{ item.scenario }}</span>
                  <span v-if="item.attachments.length" class="block truncate text-xs text-gray-400">{{ item.attachments.length }} 个附件</span>
                </span>
              </div>
              <button
                v-if="canEdit"
                type="button"
                class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-primary dark:hover:bg-gray-800"
                title="编辑这条示例"
                aria-label="编辑"
                @click="openExampleEditor(index)"
              >
                <PencilSquareIcon class="h-4 w-4" />
              </button>
              <button
                v-if="canEdit"
                type="button"
                class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-red-500 dark:hover:bg-gray-800"
                title="删除这条示例"
                aria-label="删除"
                @click="askDeleteExample(index)"
              >
                <TrashIcon class="h-4 w-4" />
              </button>
            </div>
          </div>
          <div v-if="canEdit" class="shrink-0 border-t border-gray-100 p-3 dark:border-gray-700">
            <button
              type="button"
              class="flex w-full items-center justify-center rounded-xl px-3 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
              :style="{ backgroundColor: 'var(--primary-color, #1677ff)' }"
              :disabled="exampleDraft.length >= 20 || savingExamples"
              @click="openExampleEditor(null)"
            >
              添加示例
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div
        v-if="showExampleEditor"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/20 p-4 backdrop-blur-sm"
        @click.self="showExampleEditor = false"
      >
        <div class="flex max-h-[min(40rem,80vh)] w-full max-w-[48rem] flex-col overflow-visible rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800">
          <div class="flex items-center justify-between rounded-t-xl border-b border-gray-100 bg-gray-50 px-6 py-4 dark:border-gray-700 dark:bg-gray-800/50">
            <h3 class="text-base font-bold text-gray-800 dark:text-gray-200">{{ editingExampleIndex === null ? '新建示例' : '编辑示例' }}</h3>
            <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="showExampleEditor = false">
              <XMarkIcon class="h-4 w-4" />
            </button>
          </div>
          <div class="flex min-h-0 flex-1 flex-col space-y-4 overflow-y-auto p-6">
            <div>
              <label class="mb-1 block text-[10px] font-bold uppercase text-gray-400">名称</label>
              <input v-model="exampleForm.label" type="text" maxlength="50" placeholder="如：附件整改下发" class="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-3 text-sm outline-none transition-all focus:ring-1 focus:ring-primary dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100" />
            </div>
            <div class="flex min-h-[8rem] flex-col">
              <label class="mb-1 block text-[10px] font-bold uppercase text-gray-400">指令内容</label>
              <div class="relative flex min-h-[8rem] flex-1 flex-col">
                <div
                  v-if="exampleSkillQuery !== null && !exampleSkillMenuDismissed"
                  class="absolute bottom-full left-0 right-0 z-20 mb-2 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800"
                >
                  <div class="flex items-center gap-1 border-b border-gray-200 px-2.5 dark:border-gray-700">
                    <span class="mb-2 h-3.5 w-1 shrink-0 rounded-full bg-primary" />
                    <span class="relative px-2 pb-2 pt-2 text-xs font-semibold text-gray-900 dark:text-gray-100">
                      技能
                      <span class="ml-1 rounded-md bg-primary/10 px-1.5 py-0.5 text-[9px] font-bold text-primary">{{ filteredExampleSkills.length }}</span>
                    </span>
                  </div>
                  <div ref="exampleSkillListRef" class="max-h-48 overflow-y-auto px-1.5 py-1.5">
                    <div v-if="promptSkillsLoading" class="flex h-16 items-center justify-center text-[11px] text-gray-400">正在加载技能…</div>
                    <div v-else-if="!filteredExampleSkills.length" class="flex h-16 items-center justify-center text-[11px] text-gray-400">暂无匹配技能</div>
                    <button
                      v-for="(skill, skillIndex) in filteredExampleSkills"
                      :key="skill.id"
                      type="button"
                      class="flex h-12 w-full items-center gap-2 rounded-lg px-2 text-left hover:bg-amber-50 dark:hover:bg-amber-950/40"
                      :class="skillIndex === exampleSkillActiveIndex ? 'bg-amber-50 ring-1 ring-amber-200/70' : ''"
                      @mouseenter="exampleSkillActiveIndex = skillIndex"
                      @mousedown.prevent
                      @click="pickExampleSkill(skill)"
                    >
                      <PuzzlePieceIcon class="h-4 w-4 shrink-0 text-amber-600" aria-hidden="true" />
                      <span class="min-w-0 flex-1 truncate text-[12px] text-gray-800 dark:text-gray-100">{{ skill.name || skill.id }}</span>
                    </button>
                  </div>
                </div>
                <div class="relative flex min-h-[8rem] flex-1 flex-col overflow-hidden rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 focus-within:ring-1 focus-within:ring-primary dark:border-gray-700 dark:bg-gray-900">
                  <div v-if="exampleForm.skill" ref="exampleSkillRowRef" class="absolute left-3 top-3 z-20 flex h-5 items-center" :style="{ transform: `translateY(-${exampleSkillScrollTop}px)` }">
                    <span class="group/skill inline-flex h-5 max-w-full items-center rounded-full bg-gray-100 px-2 text-sm leading-none text-gray-700 dark:bg-gray-700 dark:text-gray-100">
                      <button type="button" class="mr-1 text-gray-500" aria-label="移除技能" @mousedown.prevent @click.stop="exampleForm.skill = null">
                        <XMarkIcon class="h-3 w-3" />
                      </button>
                      <span class="truncate">{{ exampleForm.skill.name }}</span>
                    </span>
                  </div>
                  <textarea
                    ref="exampleCommandRef"
                    v-model="exampleForm.command"
                    placeholder="输入要发送给 AI 的文字，输入 / 选择技能"
                    class="min-h-[7rem] w-full flex-1 resize-none bg-transparent py-1 text-sm leading-6 text-gray-900 outline-none dark:text-gray-100"
                    :style="exampleSkillIndent ? { textIndent: `${exampleSkillIndent}px` } : undefined"
                    @scroll="syncExampleSkillScroll"
                    @keydown="handleExampleCommandKeydown"
                  />
                </div>
              </div>
            </div>
            <div>
              <div class="mb-1 flex items-center justify-between">
                <label class="block text-[10px] font-bold uppercase text-gray-400">附件</label>
                <button
                  v-if="canEdit"
                  type="button"
                  class="inline-flex items-center gap-1 text-xs text-primary disabled:text-gray-300"
                  :disabled="uploadingExampleFiles || exampleForm.attachments.length >= 10"
                  @click="exampleFileInputRef?.click()"
                >
                  <PaperClipIcon class="h-3.5 w-3.5" />
                  {{ uploadingExampleFiles ? '上传中…' : '上传附件' }}
                </button>
              </div>
              <input ref="exampleFileInputRef" type="file" multiple class="hidden" @change="onExampleFileChange" />
              <div
                class="flex min-h-[9rem] flex-col rounded-lg border border-dashed px-3 py-4 transition-colors"
                :class="[
                  exampleFileDragging ? 'border-primary bg-primary/5' : 'border-gray-200 dark:border-gray-700',
                  exampleForm.attachments.length ? 'justify-start' : 'items-center justify-center',
                ]"
                @dragenter.prevent="exampleFileDragging = canEdit"
                @dragover.prevent="exampleFileDragging = canEdit"
                @dragleave="onExampleDragLeave"
                @drop.prevent="onExampleFileDrop"
              >
                <div v-if="!exampleForm.attachments.length" class="text-center text-xs leading-5 text-gray-400">把文件拖到这里，或点上方上传<br />最多 10 个，单个不超过 20MB</div>
                <div v-else class="space-y-1">
                  <div
                    v-for="(file, fileIndex) in exampleForm.attachments"
                    :key="file.url"
                    class="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700 dark:bg-gray-900 dark:text-gray-200"
                  >
                    <PaperClipIcon class="h-4 w-4 shrink-0 text-gray-400" />
                    <span class="min-w-0 flex-1 truncate">{{ file.filename }}</span>
                    <button type="button" class="text-gray-400 hover:text-red-500" aria-label="移除附件" @click="removeExampleAttachment(fileIndex)">
                      <XMarkIcon class="h-4 w-4" />
                    </button>
                  </div>
                  <p class="pt-1 text-[11px] text-gray-400">继续把文件拖到这里即可添加</p>
                </div>
              </div>
            </div>
            <div>
              <label class="mb-1 block text-[10px] font-bold uppercase text-gray-400">使用场景</label>
              <input v-model="exampleForm.scenario" type="text" maxlength="200" placeholder="说明这条示例做什么，例如：把附件里的问题整理成企业整改任务" class="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-3 text-sm outline-none transition-all focus:ring-1 focus:ring-primary dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100" />
            </div>
            <button
              type="button"
              class="w-full shrink-0 rounded-lg bg-primary py-3 text-sm font-bold text-white shadow-md shadow-primary/20 transition-all hover:opacity-90 disabled:opacity-50"
              :style="{ backgroundColor: 'var(--primary-color, #1677ff)' }"
              :disabled="savingExamples || uploadingExampleFiles || !exampleForm.label.trim() || (!exampleForm.command.trim() && !exampleForm.skill && !exampleForm.attachments.length)"
              @click="submitExampleEditor"
            >
              {{ savingExamples ? '保存中…' : (editingExampleIndex === null ? '添加示例' : '保存修改') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

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
    <ConfirmModal
      v-if="showDeletePromptConfirm"
      title="删除快捷指令"
      :message="`确定要删除指令 [${promptDraft[promptPendingDelete ?? -1]?.label || ''}] 吗？`"
      type="danger"
      confirm-text="删除"
      @confirm="executeDeletePrompt"
      @cancel="showDeletePromptConfirm = false"
    />
    <ConfirmModal
      v-if="showDeleteExampleConfirm"
      title="删除示例"
      :message="`确定要删除示例 [${exampleDraft[examplePendingDelete ?? -1]?.label || ''}] 吗？`"
      type="danger"
      confirm-text="删除"
      @confirm="executeDeleteExample"
      @cancel="showDeleteExampleConfirm = false"
    />
  </div>
</template>

<style scoped>
@keyframes slide-in-right {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
.animate-slide-in-right {
  animation: slide-in-right 0.28s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
</style>
