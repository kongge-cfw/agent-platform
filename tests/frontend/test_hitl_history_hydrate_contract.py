"""Contract tests for restoring HITL cards from persisted process_timeline."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_infrastructure


def _run_typescript(module_path: str, expression: str):
    script = f"""
(async () => {{
const fs = require('fs');
const path = require('path');
const ts = require('./frontend/node_modules/typescript');
const utilsDir = {json.dumps(str(ROOT / "frontend/src/utils"))};
const requireTs = (id) => {{
  if (id.startsWith('./') || id.startsWith('../')) {{
    const resolved = path.resolve(utilsDir, id);
    const filePath = resolved.endsWith('.ts') ? resolved : resolved + '.ts';
    if (fs.existsSync(filePath)) {{
      const nested = fs.readFileSync(filePath, 'utf8');
      const nestedCode = ts.transpileModule(nested, {{
        compilerOptions: {{ module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }}
      }}).outputText;
      const nestedRef = {{ exports: {{}} }};
      new Function('module', 'exports', 'require', nestedCode)(nestedRef, nestedRef.exports, requireTs);
      return nestedRef.exports;
    }}
  }}
  return require(id);
}};
const source = fs.readFileSync({json.dumps(module_path)}, 'utf8');
const code = ts.transpileModule(source, {{
  compilerOptions: {{ module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }}
}}).outputText;
const moduleRef = {{ exports: {{}} }};
new Function('module', 'exports', 'require', code)(moduleRef, moduleRef.exports, requireTs);
const api = moduleRef.exports;
const result = await (async () => {{ {expression} }})();
process.stdout.write(JSON.stringify(result));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_hitl_history_restores_pending_cards_and_receipts():
    result = _run_typescript(
        "frontend/src/utils/hitlHistory.ts",
        """
const pending = {};
api.attachHitlCardsFromTimeline(pending, [
  {
    kind: 'hitl',
    id: 'business_confirmation_bc_1',
    card_type: 'business_confirmation',
    status: 'pending',
    payload: {
      type: 'business_confirmation',
      confirmation_id: 'bc_1',
      title: '请确认供应商',
      fields: [{ key: 'supplier_name', label: '供应商名称', value: '北京神马' }],
      confirm_label: '确定',
      cancel_label: '取消',
    },
  },
  {
    kind: 'hitl',
    id: 'user_question_uq_1',
    card_type: 'user_question',
    status: 'pending',
    payload: {
      type: 'user_question',
      question_id: 'uq_1',
      question: '按什么维度统计？',
      options: [{ id: 'daily', label: '按天' }, { id: 'monthly', label: '按月' }],
    },
  },
  {
    kind: 'hitl',
    id: 'permission_required_perm_1',
    card_type: 'permission_required',
    status: 'pending',
    payload: {
      type: 'permission_required',
      permission_request_id: 'perm_1',
      title: '需要确认工具调用: bash',
      details: 'ls',
      tool_call: { name: 'bash' },
    },
  },
  {
    kind: 'hitl',
    id: 'grounding_blocked_grounding_blocked',
    card_type: 'grounding_blocked',
    status: 'pending',
    payload: {
      type: 'grounding_blocked',
      title: '暂时无法验证事实',
      message: '缺少来源',
      actions: [{ id: 'retry', label: '重新检索', style: 'primary', kind: 'grounding_retry' }],
    },
  },
]);
const answered = [
  {
    role: 'agent',
    businessConfirmation: { ...pending.businessConfirmation },
    userQuestion: { ...pending.userQuestion },
    pendingPermission: { ...pending.pendingPermission },
  },
  { role: 'user', content: '【业务确认】用户已确定\\nconfirmation_id: bc_1' },
];
api.resolveHitlCardsInHistory(answered);
const stale = [
  {
    role: 'agent',
    pendingPermission: { permission_request_id: 'perm_old', status: 'pending', title: '旧', details: '' },
    pendingExternalExecution: { external_execution_request_id: 'ext_old', status: 'pending', title: '旧', details: '' },
  },
  { role: 'user', content: '继续' },
];
api.resolveHitlCardsInHistory(stale);
return {
  confirmationId: pending.businessConfirmation.confirmation_id,
  question: pending.userQuestion.question,
  permissionId: pending.pendingPermission.permission_request_id,
  groundingTitle: pending.groundingBlocked.title,
  answeredStatus: answered[0].businessConfirmation.status,
  answeredDecision: answered[0].businessConfirmation.decision,
  expiredPermission: stale[0].pendingPermission.status,
  expiredExternal: stale[0].pendingExternalExecution.status,
  resume: api.historyHasActionableResumeCard([
    { role: 'agent', pendingPermission: { status: 'pending' } },
  ]),
};
""",
    )
    assert result["confirmationId"] == "bc_1"
    assert result["question"] == "按什么维度统计？"
    assert result["permissionId"] == "perm_1"
    assert result["groundingTitle"] == "暂时无法验证事实"
    assert result["answeredStatus"] == "submitted"
    assert result["answeredDecision"] == "confirmed"
    assert result["expiredPermission"] == "expired"
    assert result["expiredExternal"] == "error"
    assert result["resume"] is True


def test_hitl_history_successful_continuation_finishes_prior_checklist():
    result = _run_typescript(
        "frontend/src/utils/hitlHistory.ts",
        """
const messages = [
  {
    role: 'agent',
    status: 'awaiting_user',
    businessConfirmation: {
      confirmation_id: 'bc_1',
      status: 'pending',
      fields: [],
    },
    processTimeline: [{
      kind: 'todo',
      todos: [
        { content: '解析企业', status: 'completed' },
        { content: '生成确认卡', status: 'in_progress' },
        { content: '下发任务', status: 'pending' },
      ],
    }],
  },
  {
    role: 'user',
    content: '【业务确认】用户已确定\\nconfirmation_id: bc_1',
  },
  {
    role: 'agent',
    status: 'success',
    content: '已完成任务下发',
  },
];
api.resolveHitlCardsInHistory(messages);
const unrelated = [
  {
    role: 'agent',
    status: 'error',
    processTimeline: [{
      kind: 'todo',
      todos: [{ content: '失败旧任务', status: 'in_progress' }],
    }],
  },
  { role: 'user', content: '新的普通问题' },
  { role: 'agent', status: 'success', content: '普通回答' },
];
api.resolveHitlCardsInHistory(unrelated);
const interrupted = [
  {
    role: 'agent',
    status: 'awaiting_user',
    businessConfirmation: {
      confirmation_id: 'bc_interrupted',
      status: 'pending',
      fields: [],
    },
    processTimeline: [{
      kind: 'todo',
      todos: [{ content: '旧任务', status: 'in_progress' }],
    }],
  },
  {
    role: 'user',
    content: '【业务确认】用户已确定\\nconfirmation_id: bc_interrupted',
  },
  { role: 'user', content: '开始一个新任务' },
  { role: 'agent', status: 'success', content: '新任务已完成' },
];
api.resolveHitlCardsInHistory(interrupted);
return {
  decision: messages[0].businessConfirmation.decision,
  statuses: messages[0].processTimeline[0].todos.map(item => item.status),
  unrelatedStatus: unrelated[0].processTimeline[0].todos[0].status,
  interruptedStatus: interrupted[0].processTimeline[0].todos[0].status,
};
""",
    )

    assert result == {
        "decision": "confirmed",
        "statuses": ["completed", "completed", "completed"],
        "unrelatedStatus": "in_progress",
        "interruptedStatus": "in_progress",
    }


def test_hitl_history_wiring_covers_embed_and_debug():
    embed = (ROOT / "frontend/src/views/EmbedChat.vue").read_text(encoding="utf-8")
    debug = (ROOT / "frontend/src/views/AgentDebug.vue").read_text(encoding="utf-8")
    snapshot = (
        ROOT / "app/services/ai/runtime/agentscope/process_timeline_snapshot.py"
    ).read_text(encoding="utf-8")
    timeline = (ROOT / "frontend/src/utils/processTimeline.ts").read_text(encoding="utf-8")
    chat_api = (ROOT / "app/api/v1/endpoints/chat.py").read_text(encoding="utf-8")

    assert "attachHitlCardsFromTimeline" in embed
    assert "resolveHitlCardsInHistory" in embed
    assert "attachHitlCardsFromTimeline" in debug
    assert "resolveHitlCardsInHistory" in debug
    assert "status: item.status" in embed
    assert "status: m.status" in debug
    assert "status: Optional[str] = None" in chat_api
    assert '"status": r.status' in chat_api
    assert '"kind": "hitl"' in snapshot
    assert '"business_confirmation"' in snapshot
    assert '"permission_required"' in snapshot
    assert '"external_execution_required"' in snapshot
    assert '"grounding_blocked"' in snapshot
    assert 'item.kind === "hitl"' in timeline
