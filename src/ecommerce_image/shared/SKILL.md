---
name: ecommerce-image-shared
description: 电商图片生成与审核的共享模块（shared module for ecommerce-image workflow）
category: ecommerce-image
---

# ecommerce-image shared module

## 概述

提供 ecommerce-image workflow 的共享工具，包括 Git 操作、Prompt 模板、状态管理。

## 目录结构

```
shared/
├── git_ops.py     # Git 操作封装
├── prompts.py      # Prompt 模板
└── utils.py        # 通用工具
```

## git_ops.py

Git 操作封装，用于持久化任务状态。

### 核心函数

| 函数 | 说明 |
|------|------|
| `init_repo()` | 初始化仓库，创建目录结构 |
| `add(path)` | Stage 文件 |
| `commit(message)` | 提交变更 |
| `tag(tag_name, ref)` | 创建标签 |
| `diff(path)` | 获取变更列表 |
| `log(path, max_count)` | 获取提交日志 |
| `auto_rescue_commit()` | 自动提交未保存的变更（防止遗忘）|

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ECOMMERCE_IMAGE_REPO` | `/home/admin/ecommerce-image` | Git 仓库路径 |

## prompts.py

### User Story

| 函数 | 说明 |
|------|------|
| `parse_user_input(text)` | 解析用户输入，提取结构化信息 |
| `build_user_story(params)` | 构建 User Story 文件内容 |
| `build_image_prompt(story)` | 构建 gpt-image-2 生成 prompt |
| `build_judge_prompt(story)` | 构建 LLM Judge prompt |
| `parse_judge_result(text)` | 解析 Judge 输出 |

### Prompt 模板

- `IMAGE_PROMPT_TEMPLATE`: gpt-image-2 生成指令
- `JUDGE_PROMPT_TEMPLATE`: LLM Judge 审核指令

## utils.py

### 状态管理

| 函数 | 说明 |
|------|------|
| `load_metadata(story_id)` | 加载任务元数据 |
| `save_metadata(story_id, data)` | 保存任务元数据 |
| `update_story_status(story_id, status)` | 更新任务状态 |
| `load_user_story(story_id)` | 加载 User Story |
| `save_user_story(story_id, content)` | 保存 User Story |
| `generate_story_id()` | 生成唯一任务 ID |

### 文件操作

| 函数 | 说明 |
|------|------|
| `get_output_path(story_id, filename)` | 获取输出路径 |
| `save_feedback(story_id, type, content)` | 保存用户反馈 |
| `read_feedback(story_id)` | 读取用户反馈 |
| `compress_image_for_feishu(path)` | 压缩图片用于飞书卡片 |

### 辅助函数

| 函数 | 说明 |
|------|------|
| `format_timestamp(dt)` | 格式化时间戳 |
| `get_user_display_name(user_id)` | 获取用户显示名 |

## 依赖

- Python 3.8+
- Pillow（图片压缩）
- Git（需安装并配置）

## 使用示例

```python
from shared import git_ops, prompts, utils

# 初始化
git_ops.init_repo()

# 解析用户输入
parsed = prompts.parse_user_input("生成夏季连衣裙主图，SKU: DRESS-S-001，¥299")

# 构建 prompt
prompt = prompts.build_image_prompt(parsed)

# 保存元数据
utils.save_metadata("us-20260429-001", {"status": "generating"})
```
