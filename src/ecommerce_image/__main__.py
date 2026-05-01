#!/usr/bin/env python3
"""
ecommerce-image 主入口
用法:
  python __main__.py start "<用户需求>" <user_open_id>
  python __main__.py status <story_id>
  python __main__.py callback <action> <story_id> [feedback]
  python __main__.py run <story_id>        # 从当前状态继续执行
"""
import sys
import os
import json
import subprocess
from datetime import datetime
from pathlib import Path

# 添加 shared 路径
SKILL_DIR = Path(__file__).parent
REPO_ROOT = Path(os.environ.get('ECOMMERCE_IMAGE_REPO', '/home/admin/ecommerce-image'))

sys.path.insert(0, str(SKILL_DIR / 'shared'))
from utils import load_metadata, save_metadata, update_story_status, load_user_story


def ensure_env():
    """确保环境变量加载"""
    if not os.environ.get('NVIDIA_API_KEY'):
        env_file = Path.home() / '.hermes' / '.env'
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith('NVIDIA_API_KEY='):
                    key = line.split('=', 1)[1].strip().strip('"').strip("'")
                    os.environ['NVIDIA_API_KEY'] = key
                elif line.startswith('OPENROUTER_API_KEY='):
                    key = line.split('=', 1)[1].strip().strip('"').strip("'")
                    os.environ['OPENROUTER_API_KEY'] = key


def git_commit(path, msg):
    """执行 git add + commit"""
    try:
        subprocess.run(['git', '-C', str(REPO_ROOT), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(REPO_ROOT), 'commit', '-m', msg], check=True, capture_output=True)
        print(f"  ✓ Git commit: {msg}")
    except subprocess.CalledProcessError as e:
        print(f"  ⚠ Git commit failed: {e.stderr.decode() if e.stderr else e}")


def cmd_start(message: str, user_open_id: str) -> str:
    """创建新任务，开始生成流程"""
    ensure_env()

    # 生成 story_id
    date = datetime.now().strftime('%Y%m%d')
    existing = list((REPO_ROOT / 'inbox').glob(f'*-{date}-*.md'))
    seq = len(existing) + 1
    story_id = f'us-{date}-{seq:03d}'

    print(f"[Start] story={story_id}")
    print(f"[Start] message={message}")

    # 从用户消息中解析 platforms 和 requirements
    # platforms: 常见平台关键词检测
    platform_keywords = {
        '朋友圈': '朋友圈',
        '小红书': '小红书',
        '公众号': '公众号',
        '抖音': '抖音',
        '微博': '微博',
        'Instagram': 'Instagram',
        '淘宝': '淘宝',
        '天猫': '天猫',
        '京东': '京东',
        '线下': '线下印刷',
    }
    detected_platforms = [v for k, v in platform_keywords.items() if k in message]
    platforms_str = ', '.join(detected_platforms) if detected_platforms else '待定'

    # requirements: 消息主体（去掉 title 后的内容）
    title = message[:50].strip()
    requirements_text = message.strip()

    # 创建 inbox story 文件（含 YAML frontmatter，供 judge-llm 提取需求字段）
    inbox_dir = REPO_ROOT / 'inbox'
    inbox_dir.mkdir(parents=True, exist_ok=True)
    story_file = inbox_dir / f'{story_id}.md'
    frontmatter = f"""---
title: {title}
platforms: {platforms_str}
requirements: |
  {requirements_text}
---

# User Story: {story_id}

{message}
"""
    story_file.write_text(frontmatter, encoding='utf-8')

    # 初始化 metadata
    output_dir = REPO_ROOT / 'output' / story_id
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        'title': title,
        'platforms': platforms_str,
        'requirements': requirements_text,
        'status': 'PENDING',
        'created_by': user_open_id,
        'created_at': datetime.now().isoformat(),
        'user_message': message,
        'retry_count': 0,
        'image_provider': os.environ.get('IMAGE_PROVIDER', 'nvidia'),
        'judge_provider': os.environ.get('JUDGE_PROVIDER', 'nvidia'),
    }
    save_metadata(story_id, metadata)
    git_commit(output_dir, f'[NEW] {story_id}')

    # 启动生成流程
    return cmd_run(story_id)


def cmd_run(story_id: str) -> str:
    """从当前状态继续执行"""
    ensure_env()
    metadata = load_metadata(story_id)
    status = metadata.get('status', 'PENDING')

    print(f"[Run] story={story_id} status={status}")

    if status == 'PENDING':
        update_story_status(story_id, 'GENERATING')
        return run_generate(story_id)

    elif status == 'GENERATING':
        return run_judge(story_id)

    elif status == 'JUDGE_LLM':
        return run_send_card(story_id)

    elif status == 'AWAITING_REVIEW':
        print("  → 等待用户审核（飞书卡片已发送）")
        return story_id

    elif status == 'HUMAN_INTERVENTION':
        print("  ⚠ 需要人工介入")
        return story_id

    else:
        print(f"  ? 未知状态: {status}")
        return story_id


def run_generate(story_id: str, feedback: str = None) -> str:
    """调用 worker 生成图片"""
    print("  → GENERATING: 调用 NVIDIA FLUX 生成图片...")

    script = SKILL_DIR / 'worker' / 'scripts' / 'generate.py'
    env = os.environ.copy()
    env['IMAGE_PROVIDER'] = env.get('IMAGE_PROVIDER', 'nvidia')

    cmd = [sys.executable, str(script), story_id]
    if feedback:
        cmd.append(feedback)
    result = subprocess.run(
        cmd,
        capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        print(f"  ✗ 生成失败: {result.stderr}")
        metadata = load_metadata(story_id)
        metadata['status'] = 'HUMAN_INTERVENTION'
        metadata['error'] = result.stderr
        save_metadata(story_id, metadata)
        return story_id

    print("  ✓ 图片生成完成")
    update_story_status(story_id, 'JUDGE_LLM')
    return run_judge(story_id)


def run_judge(story_id: str) -> str:
    """调用 judge-llm 审核图片"""
    print("  → JUDGE_LLM: 调用 Llama 3.2 90B Vision 审核...")

    script = SKILL_DIR / 'judge-llm' / 'scripts' / 'review.py'
    env = os.environ.copy()
    env['JUDGE_PROVIDER'] = env.get('JUDGE_PROVIDER', 'nvidia')

    result = subprocess.run(
        [sys.executable, str(script), story_id],
        capture_output=True, text=True, env=env
    )

    metadata = load_metadata(story_id)

    if result.returncode == 0 and metadata.get('judge_result', {}).get('pass'):
        print("  ✓ 审核通过 → 发送飞书卡片")
        update_story_status(story_id, 'AWAITING_REVIEW')
        return run_send_card(story_id)
    else:
        reason = metadata.get('judge_result', {}).get('reason', '未知原因')
        attempts = metadata.get('judge_attempts', 0)
        print(f"  ✗ 审核失败（尝试 {attempts}/3）: {reason[:60]}")

        if attempts >= 3:
            metadata['needs_human_intervention'] = True
            metadata['status'] = 'HUMAN_INTERVENTION'
            save_metadata(story_id, metadata)
            print("  ⚠ 连续3次失败，标记 HUMAN_INTERVENTION")
        else:
            update_story_status(story_id, 'GENERATING')
            print("  → 重新生成...")
            return run_generate(story_id)

        return story_id


def run_send_card(story_id: str) -> str:
    """发送飞书审核卡片"""
    print("  → AWAITING_REVIEW: 发送飞书卡片...")

    metadata = load_metadata(story_id)
    user_open_id = metadata.get('created_by', '')

    script = SKILL_DIR / 'judge-feishu' / 'scripts' / 'card.py'
    venv_python = REPO_ROOT / '.venv' / 'bin' / 'python'
    python_bin = str(venv_python) if venv_python.exists() else sys.executable

    result = subprocess.run(
        [python_bin, str(script), 'send', story_id, user_open_id],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        print("  ✓ 飞书卡片已发送")
    else:
        print(f"  ⚠ 卡片发送失败: {result.stderr[:100]}")

    return story_id


def cmd_callback(action: str, story_id: str, feedback: str = '') -> str:
    """处理飞书按钮回调"""
    ensure_env()

    print(f"[Callback] action={action} story={story_id}")
    metadata = load_metadata(story_id)
    output_dir = REPO_ROOT / 'output' / story_id

    if action == 'approve':
        update_story_status(story_id, 'APPROVED')
        # 移动到 approved 目录
        approved_dir = REPO_ROOT / 'approved'
        approved_dir.mkdir(exist_ok=True)
        for f in output_dir.glob('draft-*.png'):
            import shutil
            shutil.copy2(f, approved_dir / f.name)
        # Git: commit + tag
        git_commit(output_dir, f'[APPROVE] {story_id}')
        try:
            git_ops.tag(f'approved/{story_id}/v1')
        except Exception as e:
            print(f"Git tag warning: {e}")
        print(f"  ✓ 审核通过，已移动到 approved/")
        return story_id

    elif action == 'reject':
        # NOTE: status is set to GENERATING so cmd_run can resume from here
        if feedback:
            metadata['reject_feedback'] = feedback
            save_metadata(story_id, metadata)
        git_commit(output_dir, f'[REJECT] {story_id} reason={str(feedback)[:30]}')
        print(f"  ✓ 已驳回，反馈: {feedback[:50]}")
        # card.py handle has already been called — trigger generation directly
        return run_generate(story_id, feedback)

    elif action == 'modify':
        if feedback:
            metadata['modify_feedback'] = feedback
            save_metadata(story_id, metadata)
        git_commit(output_dir, f'[MODIFY] {story_id}: {str(feedback)[:30]}')
        print(f"  ✓ 标记待修改: {feedback[:50]}")
        return run_generate(story_id, feedback)

    else:
        print(f"  ? 未知 action: {action}")

    return story_id


def cmd_status(story_id: str) -> dict:
    """查询任务状态"""
    metadata = load_metadata(story_id)
    print(f"Story: {story_id}")
    print(f"Status: {metadata.get('status')}")
    print(f"Created: {metadata.get('created_at')}")
    if 'judge_result' in metadata:
        jr = metadata['judge_result']
        print(f"Judge: pass={jr.get('pass')} reason={jr.get('reason', '')[:60]}")
    drafts = list((REPO_ROOT / 'output' / story_id).glob('draft-*.png'))
    if drafts:
        print(f"Drafts: {[f.name for f in drafts]}")
    return metadata


USAGE = __doc__

if __name__ == '__main__':
    args = sys.argv[1:]

    if not args or args[0] in ('-h', '--help'):
        print(USAGE)
        sys.exit(0)

    cmd = args[0]

    if cmd == 'start':
        if len(args) < 3:
            print("用法: __main__.py start \"<需求>\" <user_open_id>")
            sys.exit(1)
        story_id = cmd_start(args[1], args[2])
        print(f"\n✓ 任务已创建: {story_id}")

    elif cmd == 'run':
        if len(args) < 2:
            print("用法: __main__.py run <story_id>")
            sys.exit(1)
        cmd_run(args[1])

    elif cmd == 'callback':
        if len(args) < 3:
            print("用法: __main__.py callback <action> <story_id> [feedback]")
            sys.exit(1)
        action, story_id = args[1], args[2]
        feedback = args[3] if len(args) > 3 else ''
        cmd_callback(action, story_id, feedback)

    elif cmd == 'card':
        # 处理飞书按钮回调（Hermes feishu adapter 转换的合成消息）
        # 用法: __main__.py card button '<json_value>'
        if len(args) < 3:
            print("用法: __main__.py card button '<json_value>'")
            sys.exit(1)
        action_tag = args[1]
        if action_tag != 'button':
            print(f"  ? 不支持的 action tag: {action_tag}")
            sys.exit(1)
        try:
            action_value = json.loads(args[2])
        except json.JSONDecodeError as e:
            print(f"  ? JSON 解析失败: {e}")
            sys.exit(1)
        action = action_value.get('action', '')
        story_id = action_value.get('story_id', '')
        feedback = action_value.get('feedback', '')
        if not story_id or not action:
            print(f"  ? 缺少 story_id 或 action: {action_value}")
            sys.exit(1)
        print(f"[Card Button] action={action} story={story_id}")
        # 传入完整 action_value（含 feedback_key），handle 在内部提取反馈
        script = SKILL_DIR / 'judge-feishu' / 'scripts' / 'card.py'
        venv_python = REPO_ROOT / '.venv' / 'bin' / 'python'
        python_bin = str(venv_python) if venv_python.exists() else sys.executable
        result = subprocess.run(
            [python_bin, str(script), 'handle', story_id, action, feedback, args[2]],
            capture_output=True, text=True
        )
        if result.stdout:
            print(result.stdout)
        if result.returncode != 0:
            print(f"  ⚠ handle failed: {result.stderr[:200]}")
            sys.exit(1)

    elif cmd == 'status':
        if len(args) < 2:
            print("用法: __main__.py status <story_id>")
            sys.exit(1)
        cmd_status(args[1])

    else:
        print(f"未知命令: {cmd}")
        print(USAGE)
        sys.exit(1)
