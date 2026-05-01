---
name: ecommerce-image-judge-feishu
description: 电商图片飞书审核 - 发送飞书审核卡片，处理用户按钮回调
category: ecommerce-image
---

# ecommerce-image-judge-feishu

## 概述

负责向用户发送包含预览图的飞书审核卡片，并处理用户的通过/驳回/修改按钮回调。

## 核心逻辑

### 发送卡片

```
输入：story_id, user_id
    │
    ▼
1. 加载 metadata
    │
    ▼
2. 获取最新 draft 图片
    │
    ▼
3. 压缩图片（<2MB）
    │
    ▼
4. 上传至飞书
    │
    ▼
5. 拼装交互卡片
    │
    ▼
6. 发送至用户
    │
    ▼
7. 更新 metadata → status: awaiting_review
    │
    ▼
输出：message_id
```

### 处理回调

```
用户点击按钮
    │
    ▼
handle_callback(action, story_id, feedback?)
    │
    ├─ approve → 移动到 approved/ → tag → 完成
    ├─ reject  → 保存feedback → status: rejected → 触发Worker重生成
    └─ modify  → 保存feedback → status: modify → 触发Worker重生成
```

## 目录结构

```
judge-feishu/
├── SKILL.md
└── scripts/
    └── card.py    # 卡片发送+回调处理
```

## card.py 接口

### `send_review_card(story_id, user_id) -> dict`

发送审核卡片给用户。

```python
{
    'message_id': str,    # 飞书消息ID
    'image_key': str      # 飞书图片key
}
```

### `handle_callback(action, story_id, feedback=None) -> dict`

处理用户按钮回调。

```python
{
    'action': str,        # approve/reject/modify
    'story_id': str,
    'success': bool,
    'message': str
}
```

### `build_review_card(story_id, metadata, image_key) -> dict`

构建飞书交互卡片 JSON。

## 飞书卡片样式

```
┌──────────────────────────────────────┐
│ 🎨 待审核：夏季连衣裙主图              │
├──────────────────────────────────────┤
│                                      │
│         [预览图片]                    │
│                                      │
├──────────────────────────────────────┤
│ SKU: DRESS-S-001                     │
│ 规格: 800x800px PNG                  │
│ 生成时间: 2026-04-29 15:00           │
│                                      │
│ LLM初审：✅ 通过 | 任务ID：us-xxx     │
├──────────────────────────────────────┤
│ [✅ 通过]  [❌ 驳回]  [🔄 修改]        │
└──────────────────────────────────────┘
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_ID` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret |

## 依赖

- `shared/` 模块
- `requests` Python 包
- `Pillow` 图片压缩

## 使用示例

```bash
# 发送审核卡片
python scripts/card.py send us-20260429-001 ou_xxx

# 处理回调
python scripts/card.py handle approve us-20260429-001
python scripts/card.py handle reject us-20260429-001 "价格字体太小"
python scripts/card.py handle modify us-20260429-001 "背景改成浅蓝色"
```

## 触发条件

1. LLM Judge 初审通过后，由主编排 Skill 调用 `send_review_card`
2. 用户点击按钮后，由飞书 SDK webhook 或轮询触发 `handle_callback`

## 注意事项

- 图片必须压缩到 <2MB 才能上传飞书
- 卡片消息有效期为 7 天
- 按钮回调需配置飞书应用的事件订阅

## 踩坑记录

### 飞书卡片按钮结构（与 Hermes Gateway 集成）

**正确的按钮结构**（与 Hermes 原生授权卡片一致）：
```json
{
    "tag": "button",
    "text": {"tag": "plain_text", "content": "✅ 通过"},
    "type": "primary",
    "value": {
        "hermes_action": "",
        "action": "approve",
        "story_id": "<story_id>"
    }
}
```

**不要加的字段**：
- `action_type: "request"` — Hermes Gateway WebSocket 模式下不需要，飞书无 `url` 时自动回传
- `callback_url` — Gateway 用 WebSocket 推送，不依赖这个字段
- `config` — 非必要

### `hermes_action` 路由语义

| `value.hermes_action` 值 | Gateway 路由目标 |
|--------------------------|-----------------|
| 非空字符串（如 `"approve"`） | `_handle_approval_card_action` → Hermes 内置审批流 |
| 空字符串 `""` | `_handle_card_action_event` → 合成 `/card <json>` → `/card` skill |

> **关键**：所有按钮用 `hermes_action: ""` 才能触发 `/card` skill 路由。`action` 字段放在 `value` 中传回。

### 飞书 `plain_text_input` 与按钮回调互斥

**不能**在审核卡片里同时放输入框 + 按钮来收集反馈：
- 飞书卡片中，`form_value`（输入框数据）和 `action_value`（按钮数据）是**两个独立字段**，不会合并
- 按钮回调只能拿到 `action_value`，拿不到 `form_value`
- 因此驳回/修改的反馈依赖用户在飞书**直接回复文字**，Worker 从消息历史提取

**正确做法**：卡片只放按钮，提示用户在飞书回复意见，Worker 收到回调后从消息历史抓取用户下一条文本作为反馈。
