---
name: ecommerce-image-judge-llm
description: 电商图片 LLM 初审 - 使用 GPT-4o 多模态模型进行自动审核
category: ecommerce-image
---

# ecommerce-image-judge-llm

## 概述

使用 GPT-4o 多模态能力对 Worker 生成的图片进行自动初审，检查内容一致性、文字准确性、格式合规性和审美基线。

## 核心逻辑

```
输入：story_id
    │
    ▼
1. 加载 User Story
    │
    ▼
2. 获取最新 draft 图片
    │
    ▼
3. 构建 Judge prompt
    │
    ▼
4. 调用 GPT-4o 多模态审核
    │
    ▼
5. 解析审核结果
    │
    ▼
├─ PASS → 更新 metadata → git commit [JUDGE PASS]
│          │
│          ▼
│        返回: pass=True
│
└─ FAIL → 更新 metadata → git commit [JUDGE FAIL]
         （最多重试3次）
```

## 审核维度

| 维度 | 检查内容 | 通过标准 |
|------|---------|---------|
| **内容一致性** | 产品品类、颜色、风格是否匹配 | 无明显不符合 |
| **文字准确性** | 价格/规格/促销语是否正确 | 无乱码/错字 |
| **格式合规性** | 尺寸/分辨率/格式 | 符合要求 |
| **审美基线** | 背景/构图/色调 | 无明显AI瑕疵 |

## 目录结构

```
judge-llm/
├── SKILL.md
└── scripts/
    └── review.py    # 审核逻辑
```

## review.py 接口

### `judge_image(story_id) -> dict`

```python
{
    'pass': bool,           # True = 通过
    'reason': str,          # 不通过原因
    'suggestion': str,      # 修改建议
    'attempts': int        # 尝试次数
}
```

### `call_multimodal_judge(image_path, prompt) -> str`

调用 GPT-4o 进行图片审核。

## 关键机制

### 重试策略

- 最多 3 次审核机会
- 每次失败都更新 metadata 记录
- 3次全失败标记 `needs_human_intervention = True`

### 强制人工介入

连续3次 LLM Judge FAIL 后，系统标记需要人工介入，不再自动重试。

## 依赖

- `shared/` 模块
- `openai` Python 包
- `OPENAI_API_KEY` 环境变量
- GPT-4o API 访问权限

## 使用示例

```bash
# 测试
python scripts/review.py us-20260429-001
```

## 触发条件

由主编排 Skill 在 Worker 生成完成后调用。
