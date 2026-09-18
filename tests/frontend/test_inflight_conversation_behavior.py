import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_infrastructure


def _run_typescript(expression: str):
    module_path = "frontend/src/utils/inflightConversation.ts"
    script = f"""
(async () => {{
const fs = require('fs');
const ts = require('./frontend/node_modules/typescript');
const source = fs.readFileSync({json.dumps(module_path)}, 'utf8');
const code = ts.transpileModule(source, {{
  compilerOptions: {{ module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }}
}}).outputText;
const moduleRef = {{ exports: {{}} }};
const requireModule = id => require(id);
new Function('module', 'exports', 'require', code)(moduleRef, moduleRef.exports, requireModule);
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


def test_inflight_stash_peek_and_history_mutex():
    result = _run_typescript(
        """
const messages = [{ role: 'user', content: '问' }, { role: 'agent', content: '半', isThinking: true }];
api.stashInflightConversation('c1', { messages, isProcessing: true, abortController: null });
const peek = api.peekInflightConversation('c1');
const skip = api.shouldSkipHistoryReplace('c1');
api.patchInflightConversation('c1', { isProcessing: false });
const patched = api.peekInflightConversation('c1');
api.discardInflightConversation('c1');
return {
  sameArray: peek.messages === messages,
  skip,
  patchedProcessing: patched.isProcessing,
  afterDiscard: api.peekInflightConversation('c1') == null,
};
"""
    )
    assert result == {
        "sameArray": True,
        "skip": True,
        "patchedProcessing": False,
        "afterDiscard": True,
    }


def test_merge_completed_run_keeps_live_content_and_fills_empty_agent():
    result = _run_typescript(
        """
const thinking = [{ role: 'user', content: '问' }, { role: 'agent', content: '', isThinking: true, id: 2, logs: [{ title: '工具' }] }];
const server = [{ role: 'user', content: '问' }, { role: 'agent', content: '完整回答', trace_id: 't1', prompt_tokens: 9, logs: [] }];
const filled = api.mergeCompletedRunIntoMessages(thinking, server);

const live = [{ role: 'user', content: '问' }, { role: 'agent', content: '完整回答加长', trace_id: 't1', id: 8 }];
const shorter = [{ role: 'agent', content: '完整回答', trace_id: 't1', prompt_tokens: 12 }];
const kept = api.mergeCompletedRunIntoMessages(live, shorter);

const historyOnly = [{ role: 'agent', content: '旧轮', isHistory: true, trace_id: 'old' }];
const newer = [{ role: 'user', content: '新问' }, { role: 'agent', content: '新答', trace_id: 'new' }];
const replaced = api.mergeCompletedRunIntoMessages(historyOnly, newer);

const missing = api.mergeCompletedRunIntoMessages(
  [{ role: 'user', content: '问' }],
  [{ role: 'user', content: '问' }],
);

const placeholder = [
  { role: 'user', content: '旧问' },
  { role: 'agent', content: '旧答', isHistory: true, trace_id: 'old' },
  { role: 'agent', content: '', isThinking: true, id: 9 },
];
const staleServer = [
  { role: 'user', content: '旧问' },
  { role: 'agent', content: '旧答', isHistory: true, trace_id: 'old' },
];
const skippedStale = api.mergeCompletedRunIntoMessages(placeholder, staleServer);

const readyServer = [
  { role: 'user', content: '旧问' },
  { role: 'agent', content: '旧答', isHistory: true, trace_id: 'old' },
  { role: 'user', content: '新问' },
  { role: 'agent', content: '新答', isHistory: true, trace_id: 'new' },
];
const filledNew = api.mergeCompletedRunIntoMessages(placeholder, readyServer);

    return {
      filledContent: filled.messages[1].content,
      filledThinking: filled.messages[1].isThinking,
      filledId: filled.messages[1].id,
      filledLog: filled.messages[1].logs[0].title,
  keptContent: kept.messages[1].content,
  keptTokens: kept.messages[1].prompt_tokens,
  replacedTrace: replaced.messages[replaced.messages.length - 1].trace_id,
  missingUsed: missing.usedServer,
  staleUsed: skippedStale.usedServer,
  staleStillThinking: skippedStale.messages[2].isThinking,
  filledNewContent: filledNew.messages[2].content,
  filledNewTrace: filledNew.messages[2].trace_id,
};
"""
    )
    assert result == {
        "filledContent": "完整回答",
        "filledThinking": False,
        "filledId": 2,
        "filledLog": "工具",
        "keptContent": "完整回答加长",
        "keptTokens": 12,
        "replacedTrace": "new",
        "missingUsed": False,
        "staleUsed": False,
        "staleStillThinking": True,
        "filledNewContent": "新答",
        "filledNewTrace": "new",
    }


def test_generating_placeholder_only_when_run_active_without_live_agent():
    result = _run_typescript(
        """
return {
  idle: api.needsGeneratingPlaceholder([{ role: 'agent', content: '旧', isHistory: true }], false),
  historyWhileRunning: api.needsGeneratingPlaceholder([{ role: 'agent', content: '旧', isHistory: true }], true),
  thinking: api.needsGeneratingPlaceholder([{ role: 'agent', content: '', isThinking: true }], true),
  liveContent: api.needsGeneratingPlaceholder([{ role: 'agent', content: '半截' }], true),
  liveEmpty: api.needsGeneratingPlaceholder([{ role: 'agent', content: '' }], true),
  historyEmpty: api.hasLiveGeneratingAgent([{ role: 'agent', content: '', isHistory: true }]),
  greeting: api.hasLiveGeneratingAgent([{ role: 'agent', content: '您好', isGreeting: true }]),
  greetingWhileRunning: api.needsGeneratingPlaceholder([{ role: 'agent', content: '您好', isGreeting: true }], true),
  afterUser: api.needsGeneratingPlaceholder([{ role: 'user', content: '问' }], true),
};
"""
    )
    assert result == {
        "idle": False,
        "historyWhileRunning": True,
        "thinking": False,
        "liveContent": False,
        "liveEmpty": False,
        "historyEmpty": False,
        "greeting": False,
        "greetingWhileRunning": True,
        "afterUser": True,
    }
