---
name: ecommerce-image
description: 电商图片生成与审核 - 从需求到审核的完整工作流
category: ecommerce-image
commands:
  card:
    description: 处理飞书卡片按钮回调（approve/reject/modify）
    args:
      - name: action
        description: 按钮动作类型（approve/reject/modify）
      - name: story_id
        description: 任务ID
      - name: feedback
        description: 用户反馈（可选）
---

# ecommerce-image

## 概述

一个端到端的电商图片生成与审核工作流。

```
用户消息 → Prompt工程 → FLUX生图 → LLM审核 → 飞书卡片审核 → 用户最终审核
```

**两阶段核心设计**：
1. **Prompt 工程阶段**：LLM 理解用户意图，生成专业 FLUX Prompt（纯视觉描述，不含品牌/文字）
2. **图片生成阶段**：FLUX 根据优化后的 Prompt 生成，避免 AI 乱码问题

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Hermes Agent                           │
│                                                             │
│  用户消息（飞书）                                           │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────────────────────────────────────┐  │
│  │           ecommerce-image (主编排 Skill)              │  │
│  │                                                     │  │
│  │  状态机：                                            │  │
│  │  PENDING → GENERATING → JUDGE_LLM → AWAITING_REVIEW │  │
│  │       ▲                                              │  │
│  │       └────────────────── (reject/modify) ───────────┘  │
│  │                                                     │  │
│  │  子Skill调用：                                       │  │
│  │  ├── worker/generate.py    → 图片生成               │  │
│  │  ├── judge-llm/review.py   → LLM初审               │  │
│  │  └── judge-feishu/card.py  → 飞书卡片              │  │
│  │                                                     │  │
│  └─────────────────────────────────────────────────────┘  │
│                         │                                   │
└─────────────────────────│───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Git Repo: ecommerce-image                  │
│                                                             │
│  inbox/         output/         approved/     rejected/     │
│  User Story     Worker输出      审核通过       审核驳回     │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
ecommerce-image/
├── SKILL.md                    # 主编排入口
│
├── worker/
│   ├── SKILL.md
│   └── scripts/
│       └── generate.py         # NVIDIA FLUX.2-klein-4b 生图
│
├── judge-llm/
│   ├── SKILL.md
│   └── scripts/
│       └── review.py           # Llama 3.2 90B Vision 审核（NVIDIA NIM）
│
├── judge-feishu/
│   ├── SKILL.md
│   └── scripts/
│       └── card.py             # 飞书卡片+回调
│
└── shared/
    ├── SKILL.md
    ├── git_ops.py             # Git 操作
    ├── prompts.py             # Prompt 模板
    └── utils.py               # 工具函数
```

## 状态机

| 状态 | 说明 | 触发条件 |
|------|------|---------|
| `PENDING` | 等待处理 | 收到用户消息 |
| `PROMPT_GENERATING` | Prompt 工程中 | 开始调用 LLM 生成 Prompt |
| `GENERATING` | 图片生成中 | Prompt 生成完成 |
| `JUDGE_LLM` | LLM初审中 | 图片生成完成 |
| `AWAITING_REVIEW` | 等待用户审核 | LLM初审通过 |
| `APPROVED` | 审核通过 | 用户点击通过 |
| `REJECTED` | 审核驳回 | 用户点击驳回 |
| `MODIFY` | 待修改 | 用户点击修改 |
| `HUMAN_INTERVENTION` | 需要人工介入 | LLM连续3次失败 |

## 端到端流程

### 标准流程

```
1. 收到用户消息
   「生成SK2护肤产品头图」

2. PENDING → PROMPT_GENERATING
   - 调用 Prompt 生成模型（OpenRouter: ling-2.6-1t:free）
   - LLM 理解用户意图，生成纯视觉 FLUX Prompt
   - 不含任何品牌名/文字/数字，避免 FLUX 乱码问题

3. PROMPT_GENERATING → GENERATING
   - 调用 worker/generate.py
   - NVIDIA FLUX.2-klein-4b 根据优化 Prompt 生成图片

4. GENERATING → JUDGE_LLM
   - 调用 judge-llm/review.py
   - Google Gemma 4 31B (NVIDIA NIM) 多模态审核
   - PASS: 继续
   - FAIL: 返回 GENERATING（最多3次）

5. AWAITING_REVIEW
   - 调用 judge-feishu/send_card()
   - 发送飞书卡片给用户（包含生成的 Prompt + 图片）
   - 等待用户点击

6. 用户点击 → 回调处理
   ├─ [通过] → APPROVED → 移动到 approved/
   ├─ [驳回] → REJECTED → 返回 PROMPT_GENERATING（重新生成 Prompt）
   └─ [修改] → MODIFY   → 返回 PROMPT_GENERATING
```

### 异常处理

| 场景 | 处理 |
|------|------|
| Worker 生成失败 | 重试3次，失败标记 HUMAN_INTERVENTION |
| LLM Judge 连续3次 FAIL | 标记 HUMAN_INTERVENTION，通知用户 |
| **NVIDIA VL 网络超时** | **跳过 LLM 审核，直接发飞书卡片给用户人工审核** |
| 用户超时（24h） | 发送催审提醒 |
| Git 操作失败 | 记录日志，跳过（不阻塞主流程） |

## Skill 接口

### 主 Skill

#### `on_user_message(text, user_id, user_name)`

收到用户消息时触发。

```python
# 返回
{
    'story_id': 'us-20260429-001',
    'status': 'GENERATING',
    'message': '任务已创建，开始生成...'
}
```

#### `on_callback(action, story_id, feedback)`

收到飞书按钮回调时触发。

```python
# action: 'approve' | 'reject' | 'modify'
# feedback: str (for reject/modify)

# 返回
{
    'success': True,
    'next_action': 'GENERATING' | 'COMPLETE',
    'message': '处理完成'
}
```

### 飞书按钮回调处理（card skill）

Hermes Feishu 适配器把按钮点击转换为合成 COMMAND 消息 → `/card button {"action":"approve","story_id":"us-xxx"}`

→ Hermes 路由到 `/card` skill → skill 执行 `ecommerce-image/__main__.py card button '<json>'`

#### `__main__.py card` 子命令

```bash
python3 <skill-dir>/__main__.py card button '<json_value>'
# 例: card button '{"action":"approve","story_id":"us-20260501-004"}'
# 例: card button '{"action":"modify","story_id":"us-20260501-004","feedback":"背景更亮一些"}'
```

### 子 Skill

| Skill | 方法 | 说明 |
|-------|------|------|
| `worker` | `generate_image(story_id, feedback)` | 生成图片 |
| `judge-llm` | `judge_image(story_id)` | LLM 初审 |
| `judge-feishu` | `send_review_card(story_id, user_id)` | 发送卡片 |
| `judge-feishu` | `handle_callback(action, story_id, feedback)` | 处理回调 |

## 环境变量

| 变量 | 说明 |
|------|------|
| `NVIDIA_API_KEY` | NVIDIA NIM API Key（用于 FLUX 生图 + Gemma Vision 审核），存储在 `~/.hermes/.env` |
| `OPENROUTER_API_KEY` | OpenRouter API Key（用于 Prompt 生成模型），存储在 `~/.hermes/.env` |
| `IMAGE_PROVIDER` | 生图 provider：`nvidia`（默认）/ `mock` / `openai` |
| `JUDGE_PROVIDER` | 审核 provider：`nvidia`（默认）/ `mock` / `openrouter` / `openai` |
| `JUDGE_NVIDIA_MODEL` | 审核模型，默认 `google/gemma-4-31b-it` |
| `PROMPT_PROVIDER` | Prompt 生成 provider：`openrouter`（默认） |
| `FEISHU_APP_ID` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret |
| `ECOMMERCE_IMAGE_REPO` | Git 仓库路径，默认 `/home/admin/ecommerce-image` |

> **NVIDIA key 搞定生图+审核，OpenRouter key 搞定 Prompt 生成**，两者缺一不可。

## 依赖

### Python 包

```
openai>=1.0.0
requests>=2.28.0
Pillow>=9.0.0
```

### 系统依赖

- Git（需安装并配置 user.name/user.email）
- Python 3.8+

## 使用示例

### 通过 Hermes 调用

```
用户: 「生成夏季连衣裙主图，SKU: DRESS-S-001，¥299」
Hermes → ecommerce-image → worker → judge-llm → judge-feishu → 用户收到卡片
```

### 手动测试

```bash
# 初始化仓库
python -c "from shared.git_ops import init_repo; init_repo()"

# 测试生成
python worker/scripts/generate.py us-20260429-001

# 测试LLM审核
python judge-llm/scripts/review.py us-20260429-001

# 测试发送卡片（直接调函数，用venv的Python避免PIL找不到）
cd /home/admin/.hermes/skills/ecommerce-image && \
ECOMMERCE_IMAGE_REPO=/home/admin/ecommerce-image \
/home/admin/ecommerce-image/.venv/bin/python -c "
import sys; sys.path.insert(0, 'judge-feishu/scripts'); sys.path.insert(0, 'shared')
import card
card.send_review_card('us-20260501-002', 'ou_de5d301bac9ae22097273383bcc397bb')
"
```

## 下一步

1. [ ] 初始化 Git 仓库
2. [ ] 配置环境变量
3. [ ] 端到端联调
4. [ ] 配置飞书事件订阅（接收按钮回调）
5. [ ] 小范围试用

### Feishu 图片上传：必须用 curl subprocess

> 飞书 `POST /im/v1/images` 的 multipart 上传用 `requests` 库会返回 `234001 Invalid request param`，必须用 curl subprocess：
> ```python
> import subprocess, json
> result = subprocess.run([
>     'curl', '-s', '-X', 'POST',
>     'https://open.feishu.cn/open-apis/im/v1/images',
>     '-H', f'Authorization: Bearer {token}',
>     '-F', 'image_type=message',
>     '-F', f'image=@{file_path}'
> ], capture_output=True, text=True, timeout=15)
> image_key = json.loads(result.stdout)['data']['image_key']
> ```

### Feishu 卡片 action_type 必须是 "request"

> 飞书卡片按钮的 `action_type` 必须是 `request`，不能用 `share革` 或其他值：
> ```python
> {
>     "tag": "button",
>     "text": {"content": "✅ 通过", "tag": "plain_text"},
>     "type": "primary",
>     "action_type": "request",   # ← 正确
>     # "action_type": "share革"  # ← 错误，会报 11310
>     "value": {"action": "approve", "story_id": "us-xxx"}
> }
> ```

### ⚠️ 飞书卡片按钮 `hermes_action` 字段是路由关键

> Hermes Feishu Gateway 的 `_on_card_action_trigger` 根据按钮 `value` 中的 `hermes_action` 字段决定路由：
>
> | `hermes_action` 值 | 路由目标 | 适用场景 |
> |---|---|---|
> | 非空字符串（如 `"approve"`） | `_handle_approval_card_action` → 内置审批流 | 同步等待的 agent thread |
> | 空字符串 `""` | `_handle_card_action_event` → 合成 `/card` 命令 → `/card` skill | 后台 cron/异步流程 |
>
> **所有按钮必须设置 `"hermes_action": ""`**，否则回调无法路由到 `/card` skill：
> ```python
> "value": {
>     "hermes_action": "",   # ← 必须，空字符串触发 /card skill
>     "action": "approve",
>     "story_id": story_id
> }
> ```

### ⚠️ 飞书卡片 `plain_text_input` 值不会合并到按钮 `action_value`

> **结论**：不要尝试在卡片上放 `plain_text_input` 期望用户输入后点按钮时自动带上反馈。
>
> **原因**：飞书卡片中，同卡片上的 `plain_text_input` 组件值**不会**合并进按钮的 `action_value`。按钮回调只收到自己 `value` 字段的内容。
>
> **正确做法**：用户点驳回/修改按钮后，在飞书**再发一条文字消息**作为反馈。Worker 从消息历史中提取反馈内容。
>
> 当前卡片的 `reject`/`modify` 按钮 value：
> ```python
> "value": {
>     "hermes_action": "",
>     "action": "reject",    # 或 "modify"
>     "story_id": story_id
>     # 注意：不含 feedback_key，因为 Feishu 不会合并输入框的值
> }
> ```

### ⚠️ Hermes 内置审批流不适用后台任务

> Hermes Gateway 的 `resolve_gateway_approval` 机制是为**同步 agent 线程**设计的（工具调用 block 住等待审批）。电商图片是**后台 cron 流程**，用户审核时 agent 不在线。
>
> 因此不要给按钮设置 `hermes_action: "approve"`（这会尝试走内置审批流），全部用 `hermes_action: ""` 走 `/card` skill。

---

## ⚠️ judge-feishu card.py sys.path: 3 levels up to shared/

`card.py` is 3 directory levels deep from `ecommerce-image/`. The correct path insert:

```python
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'shared'))
# judge-feishu/scripts/card.py → parent.parent.parent = ecommerce-image/ ✓
```

Wrong (2 levels) → `ModuleNotFoundError: No module named 'utils'`

## ⚠️ ensure_env() must load all API keys

`__main__.py`'s `ensure_env()` only loaded `NVIDIA_API_KEY`. The Stage 1 prompt engineering calls OpenRouter (`OPENROUTER_API_KEY`), so it must be loaded too:

```python
if line.startswith('NVIDIA_API_KEY='):
    os.environ['NVIDIA_API_KEY'] = key
elif line.startswith('OPENROUTER_API_KEY='):
    os.environ['OPENROUTER_API_KEY'] = key
```

## ⚠️ Death Loop Bug: judge_attempts never increments on crash

**Problem**: When `review.py` crashes (e.g., `ModuleNotFoundError`), metadata never gets written. `judge_attempts` stays 0 forever. `__main__.py`'s `run_judge` checks `metadata.get('judge_attempts', 0) >= 3` → always false → infinite retry loop.

**Fix**: `__main__.py` must increment `judge_attempts` in metadata **before** calling the judge script (optimistic increment), not after:

```python
# In run_judge(), BEFORE calling review.py:
metadata = load_metadata(story_id)
metadata['judge_attempts'] = metadata.get('judge_attempts', 0) + 1
save_metadata(story_id, metadata)
# Then call review.py...
```

## Tips & Gotchas

### 两阶段 Prompt 工程工作流

> 核心问题：FLUX 生成文字会乱码 → 解决思路：Prompt 工程 + 纯视觉描述

**Stage 1: Prompt 生成（OpenRouter）**

使用 `inclusionai/ling-2.6-1t:free`（OpenRouter 免费模型，支持中文，输出质量高）：

```python
payload = {
    "model": "inclusionai/ling-2.6-1t:free",
    "messages": [{
        "role": "user",
        "content": """你是一个专业电商产品摄影 Prompt 工程师。
用户需求：{user_input}
格式（3行）：
ANALYSIS: [1-2句产品定位和目标用户]
PROMPT: [仅视觉描述，不含品牌/文字，FLUX可理解，1-2句]
STYLE: [5个风格关键词，逗号分隔]
"""
    }],
    "max_tokens": 300
}
```

**Stage 2: FLUX 生图（NVIDIA）**

使用生成好的纯视觉 Prompt：
```python
payload = {
    "prompt": flux_visual_prompt,  # 不含任何品牌/文字/数字
    "aspect_ratio": "1:1",
    "seed": random_seed
}
```

**可用 OpenRouter 免费模型（Prompt 生成）**：

| 模型 | 可用性 | 备注 |
|------|--------|------|
| `inclusionai/ling-2.6-1t:free` | ✅ 推荐 | 中文好，输出稳定 |
| `nvidia/nemotron-3-super-120b-a12b:free` | ✅ 可用 | 英文为主 |
| `google/gemma-4-31b-it:free` | ⚠️ 常 rate-limit | 不稳定 |

**实测输出示例**（用户输入："SK2护肤产品"）：
```
ANALYSIS: 以通透与疗愈感凸显精华质感，瓶身与肌肤形成水光呼应；克制构图放大精密细节与纯净氛围，诱发信赖与渴望。
PROMPT: 静置椭圆面霜瓶与清透滴管瓶并肩立于微润白色陶瓷台面，瓶身折射柔冷高光，背景薄雾如冰融水痕，几片半透膜质花瓣轻覆瓶肩，细腻水珠沿曲面滑落，微距呈现玻璃厚度与液体折射的层次。
STYLE: 极简通透、水光肌理、冷雾柔焦、精密微距、低饱和疗愈
```

### ⚠️ NVIDIA VL API 网络不可达时的 Fallback

**症状**：Llama 90B Vision 审核超时（90s/120s 也超），`curl https://integrate.api.nvidia.com/v1/chat/completions` 本身也超时。

**原因**：`integrate.api.nvidia.com` 从当前环境网络不可达（DNS/防火墙/路由问题），不是代码问题。

**Fallback 流程**：
```
JUDGE_LLM 超时
  → 触发 HUMAN_INTERVENTION 或直接发飞书卡片给用户
  → 用户人工审核
  → 用户回复"通过"/"重新生成"/"拒绝"
```

**手动发送图片到飞书**（NVIDIA VL 不可用时，或快速生成单张图）：
```python
import subprocess, json
from pathlib import Path

# 读取 env
env_path = Path.home() / '.hermes/.env'
for line in env_path.read_text().splitlines():
    if line.startswith('FEISHU_APP_ID='):
        FEISHU_APP_ID = line.split('=', 1)[1].strip().strip('"')
    elif line.startswith('FEISHU_APP_SECRET='):
        FEISHU_APP_SECRET = line.split('=', 1)[1].strip().strip('"')

FEISHU_API_BASE = 'https://open.feishu.cn/open-apis'

# 1. 获取 token
r = subprocess.run([
    'curl', '-s', '-X', 'POST',
    f'{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal',
    '-H', 'Content-Type: application/json',
    '-d', json.dumps({'app_id': FEISHU_APP_ID, 'app_secret': FEISHU_APP_SECRET})
], capture_output=True, text=True)
token = json.loads(r.stdout)['tenant_access_token']

# 2. 上传图片（必须用 curl subprocess，requests multipart 会报 234001）
r2 = subprocess.run([
    'curl', '-s', '-X', 'POST',
    f'{FEISHU_API_BASE}/im/v1/images',
    '-H', f'Authorization: Bearer {token}',
    '-F', 'image_type=message',
    '-F', f'image=@/path/to/image.png'
], capture_output=True, text=True)
image_key = json.loads(r2.stdout)['data']['image_key']

# 3. 发送图片消息
r3 = subprocess.run([
    'curl', '-s', '-X', 'POST',
    f'{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id',
    '-H', f'Authorization: Bearer {token}',
    '-H', 'Content-Type: application/json',
    '-d', json.dumps({
        'receive_id': 'ou_de5d301bac9ae22097273383bcc397bb',  # K哥
        'msg_type': 'image',
        'content': json.dumps({'image_key': image_key})
    })
], capture_output=True, text=True)
print(json.loads(r3.stdout).get('msg'))  # success

# 4. 可选：发送文字说明
r4 = subprocess.run([
    'curl', '-s', '-X', 'POST',
    f'{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id',
    '-H', f'Authorization: Bearer {token}',
    '-H', 'Content-Type: application/json',
    '-d', json.dumps({
        'receive_id': 'ou_de5d301bac9ae22097273383bcc397bb',
        'msg_type': 'text',
        'content': json.dumps({'text': '图片描述文字'})
    })
], capture_output=True, text=True)
```

> ⚠️ 注意：`judge-feishu/scripts/card.py` 中没有 `send_image_via_feishu` 函数，SKILL.md 旧写法是错的。上传图片必须用 curl subprocess，requests 库的 multipart 上传会返回 `234001 Invalid request param`。

**快速生成单张图片**（不走完整 story 流程）：
```bash
IMAGE_PROVIDER=nvidia /home/admin/ecommerce-image/.venv/bin/python -c "
import os, base64, requests
from pathlib import Path

# 读取 NVIDIA_API_KEY
env_path = Path.home() / '.hermes/.env'
for line in env_path.read_text().splitlines():
    if line.startswith('NVIDIA_API_KEY='):
        NVIDIA_API_KEY = line.split('=', 1)[1].strip().strip('\"')
        break

prompt = '你的图片描述'
r = requests.post(
    'https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b',
    headers={'Authorization': f'Bearer {NVIDIA_API_KEY}', 'Content-Type': 'application/json'},
    json={'prompt': prompt, 'width': 1024, 'height': 1024, 'steps': 4, 'seed': 42},
    timeout=120
)
img_bytes = base64.b64decode(r.json()['artifacts'][0]['base64'])
with open('/tmp/output.png', 'wb') as f:
    f.write(img_bytes)
"
```

**验证 NVIDIA 是否可达**：
```bash
curl -s -w "\nTime: %{time_total}s\n" -X POST \
  https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"meta/llama-3.2-90b-vision-instruct","messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],"max_tokens":5}' \
  --max-time 15
```
超时 → NVIDIA VL 不可用，需 fallback。

---

### NVIDIA NIM VL API 关键信息

| 项目 | 值 |
|------|------|
| API base URL | `https://integrate.api.nvidia.com/v1` |
| 认证 | `Authorization: Bearer nvapi-xxx`（与 FLUX 共用同一 key） |
| 模型 | `google/gemma-4-31b-it`（推荐，6s，稳定）、`meta/llama-3.2-90b-vision-instruct`（较大较慢）、`moonshotai/kimi-k2.6` |
| Key 自动加载 | 若 `NVIDIA_API_KEY` 环境变量未设置，自动从 `~/.hermes/.env` 读取 |

> ⚠️ `integrate.api.nvidia.com` 有时网络不稳定（超时），此时 LLM 审核会失败。可通过以下命令验证：
> ```bash
> curl -s -w "\nTime: %{time_total}s" -X POST \
>   https://integrate.api.nvidia.com/v1/chat/completions \
>   -H "Authorization: Bearer $NVIDIA_API_KEY" \
>   -H "Content-Type: application/json" \
>   -d '{"model":"google/gemma-4-31b-it","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' \
>   --max-time 15
> ```
> 超时请等待网络恢复或切换备选模型。

### judge-llm/review.py 路径注意

> `review.py` 在 `judge-llm/scripts/` 目录下，引用 shared 模块的正确路径是 `../../..`：
> ```python
> sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'shared'))
> ```
> 错误路径 `../../shared` 会导致 `ModuleNotFoundError: No module named 'prompts'`

### Llama Vision 输出格式

> Llama 3.2 90B Vision 输出 Markdown 标题格式（`## RESULT: FAIL`），解析正则需支持 `#` 前缀：
> ```python
> re.search(r'#{0,2}\s*RESULT:\s*PASS', text, re.IGNORECASE)
> ```
> 原始正则 `r'RESULT:\s*PASS'` 无法匹配 `## RESULT: FAIL`，会导致解析失败。

### flux.1-kontext-dev 限制

> **重要**：FLUX.1 Kontext [dev] 是 image-to-image 编辑模型，不支持用户上传任意图片。
>
> - `image` 字段只接受 `example_id`（预设示例 ID），不接受 base64 或 URL
> - 因此无法用于"给定产品图→编辑文字"的工作流
> - 若需编辑能力，需使用其他支持图片上传的编辑模型
>
> **验证命令**（会返回 `422 Expected: example_id, got: base64`）：
> ```bash
> curl -s -X POST "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-kontext-dev" \
>   -H "Authorization: Bearer $NVIDIA_API_KEY" \
>   -H "Content-Type: application/json" \
>   -d '{"prompt":"edit this","image":"data:image/png;base64,..."}'  # ← 无效
> ```

---

### FLUX 文字不稳定的本质限制

> **问题**：FLUX.2-klein-4b（及其他所有文生图模型）在生成包含文字/Logo/品牌名的图片时，文字会变成不可读的 AI 乱码伪文字。这是模型本质限制，无法通过 Prompt 优化完全解决。
>
> **实测结果**：
> - "SK2护肤产品" → 文字全是乱码 → FAIL
> - "护肤霜" → 文字不可读 → FAIL
>
> **推荐工作流**：
> 1. **两阶段**：FLUX 生成无文字的纯产品视觉图 → 后期 Figma/Photoshop 叠加准确品牌文字
> 2. **Prompt 策略**：避免在 prompt 里提品牌名/数字，只描述产品外观
> 3. **接受不完美**：若"AI 感"可接受，直接作为初稿使用
>
> **判断标准**：如果审核结果 FAIL 原因是"文字乱码"，说明是模型本质问题，重试效果有限。

---

### 可用 VL 模型对比

| 模型 | 规模 | 速度 | 推荐 |
|------|------|------|------|
| `google/gemma-4-31b-it` | 31B | ~6s | ✅ **主力审核模型**，稳定、支持 vision、多模态 |
| `meta/llama-3.2-90b-vision-instruct` | 90B | ~5-15s | 备选，`integrate.api.nvidia.com` 网络可能超时 |
| `moonshotai/kimi-k2.6` | MoE 1T | ~8s | 备选 |

### ⚠️ `openai` 包必须装入 venv，否则 NVIDIA VL judge 死循环

> `judge-llm/review.py` 调用 NVIDIA VL（`google/gemma-4-31b-it`）依赖 `openai` 包，但 venv 初始只装了 `requests`。症状：NVIDIA API 返回错误后 judge 异常退出 → metadata 不更新 → `judge_attempts` 永远是 0 → `__main__.py` 循环永不退出（连续生成 63 张图）。

**检查和修复：**
```bash
# 检查 venv 中是否有 openai
/home/admin/ecommerce-image/.venv/bin/pip list | grep openai

# 缺失则安装
/home/admin/ecommerce-image/.venv/bin/pip install openai -q
```

**临时恢复已卡死的任务：**
```python
# 重置状态，从 JUDGE_LLM 断点继续
metadata = load_metadata('us-YYYYMMDD-NNN')
metadata['status'] = 'JUDGE_LLM'
metadata.pop('needs_human_intervention', None)
save_metadata('us-YYYYMMDD-NNN', metadata)
```

### ⚠️ 死循环根因：retry 计数逻辑分散在两个文件

> `__main__.py run_judge()` 检查 `attempts >= 3` 才退出，但 `attempts` 是 `review.py` 内部更新的。如果 `review.py` 在调用 API **之前**就 crash（例如 import 失败、文件找不到），metadata 不会更新，`attempts` 永远是 0。
>
> **判断方法**：`review.py` 输出 `"attempts": 3` 但 `__main__.py` 仍然循环 → `review.py` 在 API 调用前就已退出，metadata 没写入。
>
> **解法**：在任何子脚本调用前，父进程先查 `judge_attempts` 是否已更新；或子脚本在 `call_judge()` 之前就更新 metadata。
>
> ```python
> # 安全的重试检查（父进程维度）
> attempts = metadata.get('judge_attempts', 0)
> if attempts >= MAX_JUDGE_ATTEMPTS:
>     break  # 不再调用 review.py
> ```

### ⚠️ `card.py` 的 `sys.path` 必须指向 shared 目录

> `judge-feishu/scripts/card.py` 的路径写法：
> ```python
> sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'shared'))  # ✅ 正确（3层 parent）
> sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))       # ❌ 错误（少一层）
> ```
> 错误写法会导致 `ModuleNotFoundError: No module named 'utils'`，卡片发送失败。

## 相关文档

- [Phase 1 完整方案](../docs/电商视觉素材系统-Phase1-完整方案.md)
- [飞书卡片开发文档](https://open.feishu.cn/document/ukTMukTMukTM/uADOwUjLwgDM14CM4ATN)
