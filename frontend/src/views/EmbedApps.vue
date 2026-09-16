<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ClipboardDocumentIcon, PencilSquareIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { agentApi, type AIAgent } from '../api/agent'
import { embedAppApi, type SysEmbedApp, type SysEmbedAppPayload } from '../api/embedApp'
import ConfirmModal from '../components/ConfirmModal.vue'
import { useToast } from '../composables/useToast'
import { useUser } from '../composables/useUser'
import { copyToClipboard } from '../utils/clipboard'

const { showToast } = useToast()
const { hasPermission } = useUser()
const canCreate = hasPermission('element:embed_apps:create')
const canEdit = hasPermission('element:embed_apps:edit')
const canDelete = hasPermission('element:embed_apps:delete')

const STANDARD_CLAIM_OPTIONS = [
  { key: 'subject', label: '业务用户标识', hint: '宿主系统里的登录账号，签发 Ticket 时必传', locked: true },
  { key: 'display_name', label: '展示名', hint: '对话界面显示的姓名' },
  { key: 'dept_code', label: '部门代码', hint: '南孜按部门改写行级 SQL 时使用' },
  { key: 'org_path', label: '组织路径', hint: '如 集团/上海/销售' },
  { key: 'tenant_id', label: '业务租户', hint: '开启下方「按租户隔离」时必传' },
  { key: 'extra_data', label: '业务扩展属性', hint: '如数据范围、区域等自定义字段，会传给业务 MCP' },
] as const

const ALL_CLAIM_KEYS = STANDARD_CLAIM_OPTIONS.map((item) => item.key)

const apps = ref<SysEmbedApp[]>([])
const agents = ref<AIAgent[]>([])
const loading = ref(false)
const searchQuery = ref('')
const statusFilter = ref<'all' | 'active' | 'inactive'>('all')
const showModal = ref(false)
const isEditing = ref(false)
const showDeleteConfirm = ref(false)
const deletingApp = ref<SysEmbedApp | null>(null)
const saving = ref(false)

type AppForm = SysEmbedAppPayload & { id?: string; originsText: string }

const emptyForm = (): AppForm => ({
  name: '',
  description: '',
  allowed_agent_ids: [],
  allowed_origins: [],
  require_identity: true,
  claim_keys: [...ALL_CLAIM_KEYS],
  create_shadow_user: true,
  data_permission_mode: 'nanzi_sql_rewrite',
  isolate_datasets_by_tenant: false,
  is_active: true,
  originsText: '',
})

const form = ref<AppForm>(emptyForm())

const filteredApps = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  return apps.value.filter((app) => {
    const matchesKeyword = !keyword
      || [app.app_key, app.name, app.description, ...(app.allowed_origins || [])]
        .some((value) => String(value || '').toLowerCase().includes(keyword))
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'active' && app.is_active)
      || (statusFilter.value === 'inactive' && !app.is_active)
    return matchesKeyword && matchesStatus
  })
})

const selectedClaimSet = computed(() => new Set(form.value.claim_keys || []))

const normalizeClaimKeys = (raw: string[] | undefined) => {
  const keys = [...(raw || [])]
  if (!keys.length) return [...ALL_CLAIM_KEYS]
  const selected = new Set<string>(['subject'])
  for (const key of keys) {
    if (key === 'extra_data' || key.startsWith('extra_data.')) selected.add('extra_data')
    else if (ALL_CLAIM_KEYS.includes(key as typeof ALL_CLAIM_KEYS[number])) selected.add(key)
  }
  return ALL_CLAIM_KEYS.filter((key) => selected.has(key))
}

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

const fetchAgents = async () => {
  try {
    const res = await agentApi.listAgents()
    agents.value = Array.isArray(res.data) ? res.data : ((res.data as any)?.data || [])
  } catch {
    agents.value = []
  }
}

const linesToList = (text: string) => text.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)

const openModal = (app?: SysEmbedApp) => {
  if (app) {
    isEditing.value = true
    form.value = {
      id: app.id,
      app_key: app.app_key,
      name: app.name,
      description: app.description || '',
      allowed_agent_ids: [...(app.allowed_agent_ids || [])],
      allowed_origins: [...(app.allowed_origins || [])],
      require_identity: app.require_identity !== false,
      claim_keys: normalizeClaimKeys(app.claim_keys),
      create_shadow_user: app.create_shadow_user !== false,
      data_permission_mode: app.data_permission_mode || 'nanzi_sql_rewrite',
      isolate_datasets_by_tenant: Boolean(app.isolate_datasets_by_tenant),
      is_active: app.is_active !== false,
      originsText: (app.allowed_origins || []).join('\n'),
    }
  } else {
    isEditing.value = false
    form.value = emptyForm()
  }
  showModal.value = true
}

const toggleAgent = (agentId: string) => {
  const current = new Set(form.value.allowed_agent_ids || [])
  if (current.has(agentId)) current.delete(agentId)
  else current.add(agentId)
  form.value.allowed_agent_ids = [...current]
}

const toggleClaim = (key: string, locked?: boolean) => {
  if (locked) return
  const current = new Set(form.value.claim_keys || [])
  if (current.has(key)) current.delete(key)
  else current.add(key)
  current.add('subject')
  form.value.claim_keys = ALL_CLAIM_KEYS.filter((item) => current.has(item))
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
  const payload: SysEmbedAppPayload = {
    name: form.value.name.trim(),
    description: form.value.description?.trim() || undefined,
    allowed_agent_ids: form.value.allowed_agent_ids || [],
    allowed_origins: linesToList(form.value.originsText),
    require_identity: form.value.require_identity !== false,
    claim_keys: normalizeClaimKeys(form.value.claim_keys),
    create_shadow_user: form.value.create_shadow_user !== false,
    data_permission_mode: form.value.data_permission_mode || 'nanzi_sql_rewrite',
    isolate_datasets_by_tenant: Boolean(form.value.isolate_datasets_by_tenant),
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

onMounted(() => {
  void fetchApps()
  void fetchAgents()
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-xl font-bold text-gray-900 dark:text-gray-100">嵌入应用</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          登记要嵌入对话组件的宿主系统。保存后自动生成应用 Key，宿主签发 Ticket 时带上即可。
        </p>
      </div>
      <button
        v-if="canCreate"
        type="button"
        class="rounded-md bg-primary px-3 py-2 text-sm text-white hover:bg-primary-dark"
        @click="openModal()"
      >
        + 登记应用
      </button>
    </div>

    <div class="overflow-hidden rounded-lg bg-white shadow dark:bg-gray-900">
      <div class="flex flex-col gap-3 border-b border-gray-100 p-4 dark:border-gray-800 lg:flex-row lg:items-center lg:justify-between">
        <input
          v-model="searchQuery"
          type="search"
          placeholder="搜索应用 Key、名称或域名..."
          class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-gray-700 dark:bg-gray-950 lg:w-72"
        />
        <select
          v-model="statusFilter"
          class="rounded-lg border border-gray-300 bg-white px-2.5 py-2 text-sm shadow-sm outline-none dark:border-gray-700 dark:bg-gray-950"
        >
          <option value="all">状态：全部</option>
          <option value="active">启用</option>
          <option value="inactive">停用</option>
        </select>
      </div>

      <div v-if="loading" class="p-8 text-center text-sm text-gray-400">加载中...</div>
      <div v-else-if="!filteredApps.length" class="p-8 text-center text-sm text-gray-400">暂无嵌入应用</div>
      <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
        <li v-for="app in filteredApps" :key="app.id" class="flex items-start justify-between gap-4 p-4">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-gray-900 dark:text-gray-100">{{ app.name }}</span>
              <button
                type="button"
                class="inline-flex items-center gap-1 rounded bg-gray-100 px-1.5 py-0.5 text-xs hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700"
                title="复制应用 Key"
                @click="copyAppKey(app.app_key)"
              >
                <code>{{ app.app_key }}</code>
                <ClipboardDocumentIcon class="h-3.5 w-3.5 text-gray-400" />
              </button>
              <span
                class="rounded-full px-2 py-0.5 text-xs"
                :class="app.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'"
              >{{ app.is_active ? '启用' : '停用' }}</span>
              <span class="rounded-full bg-slate-50 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {{ app.data_permission_mode === 'mcp_only' ? '权限下沉 MCP' : '南孜 SQL 改写' }}
              </span>
            </div>
            <p class="mt-1 text-sm text-gray-500">{{ app.description || '无描述' }}</p>
            <p class="mt-1 text-xs text-gray-400">
              智能体 {{ app.allowed_agent_ids?.length || 0 }} · 域名 {{ app.allowed_origins?.length || 0 }}
              · {{ app.require_identity ? '必须提交业务身份' : '允许旧代客' }}
              · {{ app.create_shadow_user ? '写入平台映射账号' : '不写平台用户表' }}
              · {{ app.isolate_datasets_by_tenant ? '按租户隔离数据集' : '不按租户切数据集' }}
            </p>
          </div>
          <div class="flex shrink-0 gap-2">
            <button v-if="canEdit" type="button" class="rounded p-1.5 text-gray-500 hover:bg-gray-100" @click="openModal(app)">
              <PencilSquareIcon class="h-5 w-5" />
            </button>
            <button
              v-if="canDelete"
              type="button"
              class="rounded p-1.5 text-red-500 hover:bg-red-50"
              @click="deletingApp = app; showDeleteConfirm = true"
            >
              <TrashIcon class="h-5 w-5" />
            </button>
          </div>
        </li>
      </ul>
    </div>

    <div v-if="showModal" class="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div class="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-5 shadow-xl dark:bg-gray-900">
        <h2 class="text-lg font-semibold">{{ isEditing ? '编辑嵌入应用' : '登记嵌入应用' }}</h2>
        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <label class="text-sm">名称
            <input v-model="form.name" class="mt-1 w-full rounded-lg border px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950" placeholder="如 CRM 门户" />
          </label>
          <label v-if="isEditing" class="text-sm">应用 Key
            <span class="mt-1 flex items-center gap-2">
              <input :value="form.app_key" disabled class="w-full rounded-lg border bg-gray-50 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950" />
              <button type="button" class="shrink-0 rounded-lg border px-2 py-2 text-xs dark:border-gray-700" @click="copyAppKey(form.app_key)">复制</button>
            </span>
            <span class="mt-1 block text-xs text-gray-400">保存后自动生成，签发 Ticket 时传入，不可修改</span>
          </label>
          <p v-else class="self-end text-xs text-gray-400">应用 Key 将在保存后自动生成，供宿主签发 Ticket 使用。</p>
          <label class="sm:col-span-2 text-sm">描述
            <input v-model="form.description" class="mt-1 w-full rounded-lg border px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950" />
          </label>
          <label class="text-sm">数据权限
            <select v-model="form.data_permission_mode" class="mt-1 w-full rounded-lg border px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950">
              <option value="nanzi_sql_rewrite">南孜改写 SQL 行级</option>
              <option value="mcp_only">不下改写，交给业务 MCP</option>
            </select>
          </label>
          <label class="flex items-center gap-2 pt-6 text-sm">
            <input v-model="form.is_active" type="checkbox" /> 启用
          </label>
          <label class="flex items-start gap-2 text-sm sm:col-span-2">
            <input v-model="form.require_identity" type="checkbox" class="mt-0.5" />
            <span>
              必须提交业务用户身份
              <span class="block text-xs font-normal text-gray-400">关闭后仍可用旧的南孜用户名代客，生产环境建议保持开启</span>
            </span>
          </label>
          <label class="flex items-start gap-2 text-sm sm:col-span-2">
            <input v-model="form.create_shadow_user" type="checkbox" class="mt-0.5" />
            <span>
              在平台用户表写入映射账号
              <span class="block text-xs font-normal text-gray-400">仅用于兼容旧会话存储，业务用户不能登录管理端。新对接可关闭，会话按业务用户标识归属。</span>
            </span>
          </label>
          <label class="flex items-start gap-2 text-sm sm:col-span-2">
            <input v-model="form.isolate_datasets_by_tenant" type="checkbox" class="mt-0.5" />
            <span>
              按业务租户隔离数据集 / 知识库
              <span class="block text-xs font-normal text-gray-400">开启后 Ticket 必须带租户，只能看见该租户或未打租户标签的资源</span>
            </span>
          </label>
          <label class="sm:col-span-2 text-sm">允许的宿主域名（每行一个，空则不限制）
            <textarea v-model="form.originsText" rows="3" class="mt-1 w-full rounded-lg border px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950" placeholder="https://crm.example.com" />
          </label>
          <div class="sm:col-span-2 text-sm">
            <p>允许宿主声明的身份字段</p>
            <p class="mt-0.5 text-xs font-normal text-gray-400">这些是固定字段。未勾选的字段即使 Ticket 传了也会被丢弃；业务用户标识始终保留。</p>
            <div class="mt-1 space-y-1 rounded-lg border p-2 dark:border-gray-700">
              <label
                v-for="option in STANDARD_CLAIM_OPTIONS"
                :key="option.key"
                class="flex items-start gap-2 rounded-md px-1 py-1"
                :class="option.locked ? 'opacity-80' : 'hover:bg-gray-50 dark:hover:bg-gray-800'"
              >
                <input
                  type="checkbox"
                  class="mt-0.5"
                  :checked="selectedClaimSet.has(option.key)"
                  :disabled="option.locked"
                  @change="toggleClaim(option.key, option.locked)"
                />
                <span>
                  {{ option.label }}
                  <code class="ml-1 text-xs text-gray-400">{{ option.key }}</code>
                  <span class="block text-xs font-normal text-gray-400">{{ option.hint }}</span>
                </span>
              </label>
            </div>
          </div>
          <div class="sm:col-span-2 text-sm">允许的智能体（空=签发人权限内均可）
            <div class="mt-1 max-h-40 overflow-y-auto rounded-lg border p-2 dark:border-gray-700">
              <label v-for="agent in agents" :key="agent.id" class="flex items-center gap-2 py-0.5">
                <input
                  type="checkbox"
                  :checked="(form.allowed_agent_ids || []).includes(agent.id)"
                  @change="toggleAgent(agent.id)"
                />
                <span>{{ agent.display_name || agent.name }}</span>
                <code class="text-xs text-gray-400">{{ agent.id }}</code>
              </label>
              <p v-if="!agents.length" class="text-xs text-gray-400">暂无智能体</p>
            </div>
          </div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="rounded-md px-3 py-2 text-sm" @click="showModal = false">取消</button>
          <button type="button" class="rounded-md bg-primary px-3 py-2 text-sm text-white disabled:opacity-60" :disabled="saving" @click="saveApp">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

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
