---
name: ecommerce-image-worker
description: 电商图片生成 Worker - 调用 gpt-image-2 生成图片
category: ecommerce-image
---

# ecommerce-image worker

## 概述

负责调用 gpt-image-2 生成电商主图，并将结果写入 Git 仓库。

## 核心逻辑

```
输入：story_id + 可选 feedback（来自驳回/修改）
    │
    ▼
1. 加载 User Story
    │
    ▼
2. 构建 gpt-image-2 prompt
    │
    ▼
3. 调用 gpt-image-2 生成图片
    │
    ▼
4. 保存到 output/{story_id}/draft-{n}.png
    │
    ▼
5. 更新 metadata.json
    │
    ▼
6. git commit [DRAFT]
    │
    ▼
输出：成功/失败 + draft_path
```

## 目录结构

```
worker/
├── SKILL.md
└── scripts/
    └── generate.py    # 核心生成逻辑
```

## generate.py 接口

### `generate_image(story_id, feedback=None) -> dict`

```python
{
    'success': bool,
    'draft_path': str,      # 输出图片路径
    'message': str,          # 状态信息
    'retry_count': int      # 重试次数
}
```

### `call_gpt_image2(prompt, size, output_path) -> bytes`

调用 gpt-image-2 API，返回图片字节流。

## 保护机制

### 重试机制

| 参数 | 值 | 说明 |
|------|-----|------|
| `MAX_RETRIES` | 3 | 最大重试次数 |
| 退避策略 | 指数退避 | 2^n 秒 |

### 循环检测

```python
if tool_call_count > MAX_TOOL_CALLS:
    raise Error('Loop detected')
```

### 版本管理

- 每次生成递增版本号：`draft-001.png`, `draft-002.png`, ...
- 保留历史版本，便于追溯

## 依赖

- `shared/` 模块
- `openai` Python 包
- `OPENAI_API_KEY` 环境变量

## 使用示例

```bash
# 测试
python scripts/generate.py us-20260429-001

# 带反馈重新生成
python scripts/generate.py us-20260429-001 "背景色改成浅蓝"
```

## 触发条件

Hermes Agent 收到用户图片生成请求后，由主编排 Skill 调用。
