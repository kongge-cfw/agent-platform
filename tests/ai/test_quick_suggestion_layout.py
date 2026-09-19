from app.services.ai.runtime.agentscope.stream_reconcile import (
    move_quick_suggestions_to_end,
    promote_recommended_questions,
    suppress_quick_suggestions,
)

import pytest

pytestmark = pytest.mark.no_infrastructure


def test_move_quick_suggestions_to_end_after_chart():
    content = """### 💡 建议
---
- 关注回款波动

### 💬 您可能还想了解
---
- [🙋 查看趋势图](quick:查看2026年各月回款率趋势图)
- [🙋 对比季度](quick:对比2025与2026年各季度回款率)

```chart
{"title": {"text": "对比图"}, "series": []}
```

（* 数据来源：财务数据集）"""
    fixed = move_quick_suggestions_to_end(content)
    assert fixed.index("```chart") < fixed.index("您可能还想了解")
    assert fixed.strip().endswith("对比2025与2026年各季度回款率)")


def test_move_quick_suggestions_keeps_already_last():
    content = """### 📊 数据概览
---
| 指标 | 数值 |
| --- | ---: |
| 回款 | 100 |

```chart
{"series": []}
```

### 💬 您可能还想了解
---
- [🙋 继续分析](quick:继续分析回款结构)"""
    assert move_quick_suggestions_to_end(content) == content


def test_move_quick_suggestions_supports_parentheses_in_sql_like_targets():
    content = """### 💬 您可能还想了解
---
- [🙋 查看用户数](quick:统计 COUNT(DISTINCT user_id) 按月趋势)

正文结果"""

    fixed = move_quick_suggestions_to_end(content)

    assert fixed.strip().endswith("统计 COUNT(DISTINCT user_id) 按月趋势)")
    assert fixed.index("正文结果") < fixed.index("您可能还想了解")


def test_promote_recommended_questions_lifts_plain_action_tail():
    content = """## ✅ 任务下发完成

可前往任务跟踪查看办理进度。

谁还没交
催一下没交的企业
查看无法匹配的企业名单"""
    promoted = promote_recommended_questions(content)
    assert "- [🙋 谁还没交](quick:谁还没交)" in promoted
    assert "- [🙋 催一下没交的企业](quick:催一下没交的企业)" in promoted
    assert "- [🙋 查看无法匹配的企业名单](quick:查看无法匹配的企业名单)" in promoted


def test_promote_recommended_questions_skips_entity_name_lists():
    content = "无法匹配企业：\n\n安达危运有限公司\n顺通物流有限公司"
    assert promote_recommended_questions(content) == content


def test_suppress_quick_suggestions_after_promote_clears_plain_tail():
    content = "结果已生成。\n\n查看任务进度\n继续分析回款结构"
    cleaned = suppress_quick_suggestions(promote_recommended_questions(content))
    assert cleaned == "结果已生成。"
    assert "quick:" not in cleaned
