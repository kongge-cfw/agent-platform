<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ChevronDownIcon, PencilSquareIcon, TrashIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { agentApi, type AIAgent } from '../api/agent'
import { uiCardApi, type SysUiCard, type SysUiCardPayload } from '../api/uiCard'
import ConfirmModal from '../components/ConfirmModal.vue'
import { useToast } from '../composables/useToast'
import { useUser } from '../composables/useUser'

const ACTION_OPTIONS = [
  { value: 'confirm', label: '确认' },
  { value: 'reject', label: '驳回' },
  { value: 'ack', label: '已知悉' },
  { value: 'close', label: '关闭' },
  { value: 'viewed', label: '已查看' },
] as const

const { showToast } = useToast()
const { hasPermission } = useUser()
const canCreate = hasPermission('element:ui_cards:create')
const canEdit = hasPermission('element:ui_cards:edit')
const canDelete = hasPermission('element:ui_cards:delete')

const cards = ref<SysUiCard[]>([])
const agents = ref<AIAgent[]>([])
const loading = ref(false)
const searchQuery = ref('')
const statusFilter = ref<'all' | 'active' | 'inactive'>('all')
const showModal = ref(false)
const isEditing = ref(false)
const showDeleteConfirm = ref(false)
const deletingCard = ref<SysUiCard | null>(null)
const saving = ref(false)
const actionMenuOpen = ref(false)
const agentMenuOpen = ref(false)
const agentSearch = ref('')
const actionPickerRef = ref<HTMLElement | null>(null)
const agentPickerRef = ref<HTMLElement | null>(null)

type CardForm = SysUiCardPayload & { id?: string }

const emptyForm = (): CardForm => ({
  card_key: '',
  name: '',
  description: '',
  render_type: 'iframe',
  url: '',
  allowed_actions: ['confirm', 'reject'],
  allowed_agent_ids: [],
  default_height: 480,
  token_ttl_seconds: 600,
  is_active: true,
})

const form = ref<CardForm>(emptyForm())

const filteredCards = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  return cards.value.filter((card) => {
    const matchesKeyword = !keyword
      || [card.card_key, card.name, card.description, card.url]
        .some((value) => String(value || '').toLowerCase().includes(keyword))
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'active' && card.is_active)
      || (statusFilter.value === 'inactive' && !card.is_active)
    return matchesKeyword && matchesStatus
  })
})

const actionOptions = computed(() => {
  const known = new Set<string>(ACTION_OPTIONS.map((item) => item.value))
  const extras = (form.value.allowed_actions || [])
    .filter((value) => value && !known.has(value))
    .map((value) => ({ value, label: value }))
  return [...ACTION_OPTIONS, ...extras]
})

const filteredAgents = computed(() => {
  const keyword = agentSearch.value.trim().toLowerCase()
  if (!keyword) return agents.value
  return agents.value.filter((agent) =>
    [agent.display_name, agent.name, agent.id, agent.description]
      .some((value) => String(value || '').toLowerCase().includes(keyword)),
  )
})

const selectedAgentItems = computed(() =>
  (form.value.allowed_agent_ids || []).map((id) => {
    const agent = agents.value.find((item) => item.id === id)
    return {
      id,
      label: agent ? (agent.display_name || agent.name) : id,
    }
  }),
)

const originsFromUrl = (url: string): string[] => {
  const text = url.trim()
  if (!text || text.startsWith('/')) return []
  try {
    const parsed = new URL(text)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return [`${parsed.protocol}//${parsed.host}`]
    }
  } catch {
    return []
  }
  return []
}

const actionLabel = (value: string) =>
  ACTION_OPTIONS.find((item) => item.value === value)?.label || value

const toggleAction = (value: string) => {
  const current = form.value.allowed_actions || []
  form.value.allowed_actions = current.includes(value)
    ? current.filter((item) => item !== value)
    : [...current, value]
}

const toggleAgent = (id: string) => {
  const current = form.value.allowed_agent_ids || []
  form.value.allowed_agent_ids = current.includes(id)
    ? current.filter((item) => item !== id)
    : [...current, id]
}

const removeAgent = (id: string) => {
  form.value.allowed_agent_ids = (form.value.allowed_agent_ids || []).filter((item) => item !== id)
}

const closeMenus = () => {
  actionMenuOpen.value = false
  agentMenuOpen.value = false
}

const onDocumentClick = (event: MouseEvent) => {
  const target = event.target as Node
  if (actionPickerRef.value && !actionPickerRef.value.contains(target)) {
    actionMenuOpen.value = false
  }
  if (agentPickerRef.value && !agentPickerRef.value.contains(target)) {
    agentMenuOpen.value = false
  }
}

const fetchCards = async () => {
  loading.value = true
  try {
    const res = await uiCardApi.list()
    cards.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    showToast(error.response?.data?.detail || '获取对话卡片失败', 'error')
  } finally {
    loading.value = false
  }
}

const fetchAgents = async () => {
  try {
    const res = await agentApi.listAgents()
    agents.value = Array.isArray(res.data) ? res.data : []
  } catch {
    try {
      const res = await agentApi.listAllowedAgents()
      agents.value = Array.isArray(res.data) ? res.data : []
    } catch (error: any) {
      showToast(error.response?.data?.detail || '获取智能体列表失败', 'error')
      agents.value = []
    }
  }
}

const openModal = (card?: SysUiCard) => {
  closeMenus()
  agentSearch.value = ''
  if (card) {
    isEditing.value = true
    form.value = {
      id: card.id,
      card_key: card.card_key,
      name: card.name,
      description: card.description || '',
      render_type: card.render_type || 'iframe',
      url: card.url,
      allowed_actions: [...(card.allowed_actions || [])],
      allowed_agent_ids: [...(card.allowed_agent_ids || [])],
      default_height: card.default_height,
      token_ttl_seconds: card.token_ttl_seconds,
      is_active: card.is_active,
    }
  } else {
    isEditing.value = false
    form.value = emptyForm()
  }
  showModal.value = true
}

const saveCard = async () => {
  if (!form.value.card_key || !form.value.name || !form.value.url) {
    showToast('请填写 card_key、名称和 URL', 'warning')
    return
  }
  const actions = [...new Set((form.value.allowed_actions || []).map((item) => item.trim()).filter(Boolean))]
  if (!actions.length) {
    showToast('请至少选择一个允许动作', 'warning')
    return
  }
  const payload: SysUiCardPayload = {
    card_key: form.value.card_key.trim(),
    name: form.value.name.trim(),
    description: form.value.description?.trim() || undefined,
    render_type: 'iframe',
    url: form.value.url.trim(),
    allowed_origins: originsFromUrl(form.value.url),
    allowed_actions: actions,
    allowed_agent_ids: form.value.allowed_agent_ids || [],
    default_height: Number(form.value.default_height) || 480,
    token_ttl_seconds: Number(form.value.token_ttl_seconds) || 600,
    is_active: form.value.is_active !== false,
  }
  saving.value = true
  try {
    if (isEditing.value && form.value.id) {
      await uiCardApi.update(form.value.id, payload)
      showToast('卡片已更新', 'success')
    } else {
      await uiCardApi.create(payload)
      showToast('卡片已创建', 'success')
    }
    showModal.value = false
    closeMenus()
    await fetchCards()
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

const requestDelete = (card: SysUiCard) => {
  deletingCard.value = card
  showDeleteConfirm.value = true
}

const confirmDelete = async () => {
  if (!deletingCard.value) return
  try {
    await uiCardApi.delete(deletingCard.value.id)
    showToast('卡片已删除', 'success')
    showDeleteConfirm.value = false
    deletingCard.value = null
    await fetchCards()
  } catch (error: any) {
    showToast(error.response?.data?.detail || '删除失败', 'error')
  }
}

onMounted(() => {
  document.addEventListener('mousedown', onDocumentClick)
  void fetchCards()
  void fetchAgents()
})

onUnmounted(() => {
  document.removeEventListener('mousedown', onDocumentClick)
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-xl font-bold text-gray-900 dark:text-gray-100">对话卡片</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          登记业务系统的复杂对话页（iframe）。智能体版本「工具能力」勾选 <code class="rounded bg-gray-100 px-1 dark:bg-gray-800">show_ui_card</code> 后，模型才能按已登记 <code class="rounded bg-gray-100 px-1 dark:bg-gray-800">card_key</code> 出卡。
        </p>
      </div>
      <button
        v-if="canCreate"
        type="button"
        class="rounded-md bg-primary px-3 py-2 text-sm text-white hover:bg-primary-dark"
        @click="openModal()"
      >
        + 登记卡片
      </button>
    </div>

    <div class="overflow-hidden rounded-lg bg-white shadow dark:bg-gray-900">
      <div class="flex flex-col gap-3 border-b border-gray-100 p-4 dark:border-gray-800 lg:flex-row lg:items-center lg:justify-between">
        <input
          v-model="searchQuery"
          type="search"
          placeholder="搜索 card_key、名称或 URL..."
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

      <div v-if="loading" class="p-8 text-center text-gray-400">加载中...</div>
      <div v-else class="overflow-x-auto">
        <table class="min-w-[960px] w-full divide-y divide-gray-200 dark:divide-gray-800">
          <thead class="bg-gray-50 dark:bg-gray-800/50">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">卡片</th>
              <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">URL</th>
              <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">允许动作</th>
              <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">状态</th>
              <th class="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200 bg-white dark:divide-gray-800 dark:bg-gray-900">
            <tr v-for="card in filteredCards" :key="card.id" class="hover:bg-gray-50 dark:hover:bg-gray-800/40">
              <td class="px-6 py-4 text-sm">
                <div class="font-medium text-gray-900 dark:text-gray-100">{{ card.name }}</div>
                <div class="font-mono text-xs text-gray-500">{{ card.card_key }}</div>
                <p v-if="card.description" class="mt-1 max-w-xs truncate text-xs text-gray-400">{{ card.description }}</p>
              </td>
              <td class="max-w-sm truncate px-6 py-4 font-mono text-sm text-gray-500" :title="card.url">{{ card.url }}</td>
              <td class="px-6 py-4 text-xs text-gray-500">{{ (card.allowed_actions || []).map(actionLabel).join('、') }}</td>
              <td class="whitespace-nowrap px-6 py-4">
                <span
                  class="inline-flex rounded-full px-2 text-xs font-semibold leading-5"
                  :class="card.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'"
                >
                  {{ card.is_active ? '启用' : '停用' }}
                </span>
              </td>
              <td class="whitespace-nowrap px-6 py-4 text-right text-sm">
                <div class="flex items-center justify-end space-x-2">
                  <button
                    v-if="canEdit"
                    type="button"
                    class="rounded-md p-1.5 text-primary hover:bg-blue-50 dark:hover:bg-blue-950/30"
                    title="编辑"
                    @click="openModal(card)"
                  >
                    <PencilSquareIcon class="h-4 w-4" />
                  </button>
                  <button
                    v-if="canDelete"
                    type="button"
                    class="rounded-md p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30"
                    title="删除"
                    @click="requestDelete(card)"
                  >
                    <TrashIcon class="h-4 w-4" />
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="filteredCards.length === 0">
              <td colspan="5" class="px-6 py-8 text-center text-sm text-gray-400">暂无匹配卡片</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="showModal" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50 p-4 backdrop-blur-sm">
      <div class="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-xl bg-white p-5 shadow-xl dark:bg-gray-900">
        <h3 class="text-lg font-bold text-gray-900 dark:text-gray-100">{{ isEditing ? '编辑对话卡片' : '登记对话卡片' }}</h3>
        <div class="mt-4 space-y-3">
          <label class="block text-sm">
            <span class="font-medium text-gray-700 dark:text-gray-300">card_key</span>
            <input v-model="form.card_key" :disabled="isEditing" class="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/20 dark:border-gray-700 dark:bg-gray-950" placeholder="platform_demo_confirm" />
          </label>
          <label class="block text-sm">
            <span class="font-medium text-gray-700 dark:text-gray-300">名称</span>
            <input v-model="form.name" class="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/20 dark:border-gray-700 dark:bg-gray-950" />
          </label>
          <label class="block text-sm">
            <span class="font-medium text-gray-700 dark:text-gray-300">URL</span>
            <input v-model="form.url" class="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/20 dark:border-gray-700 dark:bg-gray-950" placeholder="/embed/ui-card-demo 或 https://biz.example.com/card" />
          </label>
          <label class="block text-sm">
            <span class="font-medium text-gray-700 dark:text-gray-300">描述</span>
            <textarea v-model="form.description" rows="2" class="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none dark:border-gray-700 dark:bg-gray-950" />
          </label>

          <div ref="actionPickerRef" class="relative block text-sm">
            <span class="font-medium text-gray-700 dark:text-gray-300">允许动作</span>
            <button
              type="button"
              class="mt-1 flex min-h-[42px] w-full items-center justify-between gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-left text-sm outline-none focus:ring-2 focus:ring-primary/20 dark:border-gray-700 dark:bg-gray-950"
              @click="actionMenuOpen = !actionMenuOpen; agentMenuOpen = false"
            >
              <span v-if="!form.allowed_actions?.length" class="text-gray-400">请选择动作，可多选</span>
              <span v-else class="flex flex-wrap gap-1">
                <span
                  v-for="action in form.allowed_actions"
                  :key="action"
                  class="rounded-full bg-sky-50 px-2 py-0.5 text-xs text-sky-700 dark:bg-sky-900/40 dark:text-sky-200"
                >
                  {{ actionLabel(action) }}
                </span>
              </span>
              <ChevronDownIcon class="h-4 w-4 shrink-0 text-gray-400" />
            </button>
            <div
              v-if="actionMenuOpen"
              class="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-950"
            >
              <label
                v-for="option in actionOptions"
                :key="option.value"
                class="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                <input
                  type="checkbox"
                  class="rounded text-primary"
                  :checked="form.allowed_actions?.includes(option.value)"
                  @change="toggleAction(option.value)"
                />
                <span>{{ option.label }}</span>
                <span class="font-mono text-[11px] text-gray-400">{{ option.value }}</span>
              </label>
            </div>
          </div>

          <div ref="agentPickerRef" class="relative block text-sm">
            <span class="font-medium text-gray-700 dark:text-gray-300">可用智能体</span>
            <p class="mt-0.5 text-xs text-gray-400">不选则全部智能体可用</p>
            <button
              type="button"
              class="mt-1 flex min-h-[42px] w-full items-center justify-between gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-left text-sm outline-none focus:ring-2 focus:ring-primary/20 dark:border-gray-700 dark:bg-gray-950"
              @click="agentMenuOpen = !agentMenuOpen; actionMenuOpen = false"
            >
              <span v-if="!selectedAgentItems.length" class="text-gray-400">搜索并选择智能体，可多选</span>
              <span v-else class="flex flex-wrap gap-1">
                <span
                  v-for="item in selectedAgentItems"
                  :key="item.id"
                  class="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200"
                  @click.stop
                >
                  {{ item.label }}
                  <button type="button" class="text-indigo-400 hover:text-indigo-700" @click.stop="removeAgent(item.id)">
                    <XMarkIcon class="h-3 w-3" />
                  </button>
                </span>
              </span>
              <ChevronDownIcon class="h-4 w-4 shrink-0 text-gray-400" />
            </button>
            <div
              v-if="agentMenuOpen"
              class="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-950"
            >
              <div class="border-b border-gray-100 p-2 dark:border-gray-800">
                <input
                  v-model="agentSearch"
                  type="search"
                  class="w-full rounded-md border border-gray-200 px-2.5 py-1.5 text-sm outline-none focus:border-primary dark:border-gray-700 dark:bg-gray-900"
                  placeholder="搜索名称、标识或 ID"
                  @click.stop
                />
              </div>
              <div class="max-h-56 overflow-y-auto py-1">
                <p v-if="!filteredAgents.length" class="px-3 py-4 text-center text-xs text-gray-400">没有匹配的智能体</p>
                <label
                  v-for="agent in filteredAgents"
                  :key="agent.id"
                  class="flex cursor-pointer items-start gap-2 px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800"
                >
                  <input
                    type="checkbox"
                    class="mt-0.5 rounded text-primary"
                    :checked="form.allowed_agent_ids?.includes(agent.id)"
                    @change="toggleAgent(agent.id)"
                  />
                  <span class="min-w-0">
                    <span class="block font-medium text-gray-800 dark:text-gray-100">{{ agent.display_name || agent.name }}</span>
                    <span class="block font-mono text-[11px] text-gray-400">{{ agent.name }} · {{ agent.id }}</span>
                  </span>
                </label>
              </div>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <label class="block text-sm">
              <span class="font-medium text-gray-700 dark:text-gray-300">默认高度</span>
              <input v-model.number="form.default_height" type="number" min="240" max="1200" class="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none dark:border-gray-700 dark:bg-gray-950" />
            </label>
            <label class="block text-sm">
              <span class="font-medium text-gray-700 dark:text-gray-300">Token TTL（秒）</span>
              <input v-model.number="form.token_ttl_seconds" type="number" min="60" max="1800" class="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none dark:border-gray-700 dark:bg-gray-950" />
            </label>
          </div>
          <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input v-model="form.is_active" type="checkbox" class="rounded text-primary" />
            启用
          </label>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="rounded-md px-3 py-2 text-sm text-gray-500 hover:text-gray-800" @click="showModal = false; closeMenus()">取消</button>
          <button
            type="button"
            class="rounded-md bg-primary px-4 py-2 text-sm text-white disabled:opacity-60"
            :disabled="saving"
            @click="saveCard"
          >
            保存
          </button>
        </div>
      </div>
    </div>

    <ConfirmModal
      v-if="showDeleteConfirm"
      title="删除对话卡片"
      :message="`确定删除「${deletingCard?.name || ''}」？已登记的 card_key 将无法再被智能体调用。`"
      confirm-text="删除"
      @confirm="confirmDelete"
      @cancel="showDeleteConfirm = false"
    />
  </div>
</template>
