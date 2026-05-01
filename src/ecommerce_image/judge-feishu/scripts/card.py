"""
Feishu Judge: Send review cards and handle user feedback
"""
import os
import sys
import json
import base64
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'shared'))

from utils import (
    load_metadata, 
    save_metadata, 
    get_output_path, 
    compress_image_for_feishu,
    REPO_ROOT
)
import git_ops

# Feishu API
FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')
FEISHU_API_BASE = 'https://open.feishu.cn/open-apis'

def get_access_token():
    """Get Feishu tenant access token"""
    import requests
    
    url = f'{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal'
    headers = {'Content-Type': 'application/json'}
    data = {
        'app_id': FEISHU_APP_ID,
        'app_secret': FEISHU_APP_SECRET
    }
    
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    
    if result.get('code') != 0:
        raise RuntimeError(f"Failed to get access token: {result}")
    
    return result['tenant_access_token']


def upload_image(image_path: str, token: str) -> str:
    """
    Upload image to Feishu for card display.
    Returns Feishu image key.
    Must use curl subprocess — requests multipart fails with 234001.
    """
    import subprocess, json

    result = subprocess.run([
        'curl', '-s', '-X', 'POST',
        f'{FEISHU_API_BASE}/im/v1/images',
        '-H', f'Authorization: Bearer {token}',
        '-F', 'image_type=message',
        '-F', f'image=@{image_path}'
    ], capture_output=True, text=True, timeout=15)

    resp = json.loads(result.stdout)
    if resp.get('code') != 0:
        raise RuntimeError(f"Failed to upload image: {resp}")

    return resp['data']['image_key']


def send_review_card(
    story_id: str,
    user_id: str,
    receive_id_type: str = 'open_id'
) -> dict:
    """
    Send review card to user.
    
    Args:
        story_id: Task ID
        user_id: Feishu user open_id
        receive_id_type: 'open_id', 'user_id', 'union_id', 'email', 'chat_id'
        
    Returns:
        dict with message_id
    """
    import requests
    
    # Load metadata
    metadata = load_metadata(story_id)
    
    if not metadata:
        raise ValueError(f"Metadata not found for {story_id}")
    
    # Get draft path
    draft_path = metadata.get('draft_path')
    if not draft_path or not Path(draft_path).exists():
        raise ValueError(f"Draft image not found: {draft_path}")
    
    # Compress image
    compressed = compress_image_for_feishu(draft_path)
    
    # Upload to Feishu
    token = get_access_token()
    
    # Upload image
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        tmp.write(compressed)
        tmp_path = tmp.name
    
    try:
        image_key = upload_image(tmp_path, token)
    finally:
        os.unlink(tmp_path)
    
    # Build card
    card = build_review_card(story_id, metadata, image_key)
    
    # Send message
    url = f'{FEISHU_API_BASE}/im/v1/messages'
    
    params = {
        'receive_id_type': receive_id_type
    }
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'receive_id': user_id,
        'msg_type': 'interactive',
        'content': json.dumps(card)
    }
    
    response = requests.post(url, headers=headers, params=params, json=data)
    result = response.json()
    
    if result.get('code') != 0:
        raise RuntimeError(f"Failed to send card: {result}")
    
    # Update metadata (status already set to AWAITING_REVIEW by caller)
    metadata['review_sent_at'] = datetime.now().isoformat()
    metadata['review_sent_to'] = user_id
    # Persist message_id for future edits
    metadata['feishu_message_id'] = result['data']['message_id']
    save_metadata(story_id, metadata)
    
    return {
        'message_id': result['data']['message_id'],
        'image_key': image_key
    }


def build_review_card(story_id: str, metadata: dict, image_key: str) -> dict:
    """Build Feishu interactive card"""
    
    title = metadata.get('title', '图片审核')
    sku = metadata.get('sku', 'N/A')
    size = metadata.get('size', '1024x1024')
    generated_at = metadata.get('generated_at', '')
    if generated_at:
        # Format time
        try:
            dt = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
            generated_at = dt.strftime('%Y-%m-%d %H:%M')
        except:
            pass
    
    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🎨 待审核：{title}"
            },
            "template": "blue"
        },
        "elements": [
            {
                "tag": "img",
                "img_key": image_key,
                "alt": {
                    "tag": "plain_text",
                    "content": "预览图"
                }
            },
            {
                "tag": "hr"
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**SKU**: {sku}\n**规格**: {size}px\n**生成时间**: {generated_at}"
                }
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"LLM初审：✅ 通过 | 任务ID：{story_id}"
                    }
                ]
            },
            {
                "tag": "hr"
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "💡 **驳回/修改时，请在下方回复意见，Worker 将自动带上您的反馈重新生成。**"
                }
            },
            {
                "tag": "hr"
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "✅ 通过"
                        },
                        "type": "primary",
                        "value": {
                            "hermes_action": "",
                            "action": "approve",
                            "story_id": story_id
                        }
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "❌ 驳回"
                        },
                        "type": "danger",
                        "value": {
                            "hermes_action": "",
                            "action": "reject",
                            "story_id": story_id
                        }
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "🔄 修改"
                        },
                        "type": "default",
                        "value": {
                            "hermes_action": "",
                            "action": "modify",
                            "story_id": story_id
                        }
                    }
                ]
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "💡 点击按钮进行审核，驳回/修改时消息回复将作为反馈"
                    }
                ]
            }
        ]
    }


def handle_callback(action: str, story_id: str, feedback: str = None, action_value: dict = None) -> dict:
    """
    Handle user button click callback.
    
    Args:
        action: 'approve', 'reject', 'modify'
        story_id: Task ID
        feedback: User feedback text (for reject/modify). May also be embedded
                  in action_value['feedback_key'] when Feishu merges input values.
        action_value: Raw action_value dict from Feishu card callback.
                      When a plain_text_input shares the card with buttons, Feishu
                      merges all values into one dict: {action, story_id, feedback_key, <input_value>}.
                      We extract feedback from the named input field here.
    
    Returns:
        dict with result
    """
    from utils import save_feedback
    
    metadata = load_metadata(story_id)
    
    if not metadata:
        raise ValueError(f"Metadata not found for {story_id}")
    
    # ── Extract feedback from action_value if feedback_key is present ──────────
    # Feishu merges the plain_text_input value into the button's action_value
    # using the input's action_id as the key. We use feedback_key to locate
    # the user's text input in the merged dict.
    if action_value and feedback is None:
        feedback_key = action_value.get("feedback_key")
        if feedback_key and feedback_key in action_value:
            feedback = action_value.get(feedback_key, "")
    
    result = {
        'action': action,
        'story_id': story_id,
        'success': False
    }
    
    if action == 'approve':
        # NOTE: all operations (status update, file copy, git commit/tag) are
        # done by __main__.py cmd_callback — nothing to do here
        result['success'] = True
        result['message'] = '已通过审核'

    elif action == 'reject':
        # Save feedback
        if feedback:
            save_feedback(story_id, 'reject', feedback)

        # NOTE: status update is done by __main__.py cmd_callback
        # Git commit (captures current output state before regeneration)
        try:
            git_ops.add(str(REPO_ROOT / 'output' / story_id))
            git_ops.commit(f'[REJECT] {story_id}')
        except Exception as e:
            print(f"Git warning: {e}")

        result['success'] = True
        result['message'] = '已驳回'

    elif action == 'modify':
        # Save feedback
        if feedback:
            save_feedback(story_id, 'modify', feedback)

        # NOTE: status update is done by __main__.py cmd_callback
        # Git commit
        try:
            git_ops.add(str(REPO_ROOT / 'output' / story_id))
            git_ops.commit(f'[MODIFY] {story_id}')
        except Exception as e:
            print(f"Git warning: {e}")

        result['success'] = True
        result['message'] = '已提交修改意见'
    
    else:
        result['message'] = f'Unknown action: {action}'
    
    return result


def main():
    """CLI entry point"""
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python card.py send <story_id> <user_id>")
        print("  python card.py handle <action> <story_id> [feedback]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    story_id = sys.argv[2]
    
    if cmd == 'send':
        user_id = sys.argv[3] if len(sys.argv) > 3 else ''
        if not user_id:
            print("Error: user_id required")
            sys.exit(1)
        
        result = send_review_card(story_id, user_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
    elif cmd == 'handle':
        action = sys.argv[3] if len(sys.argv) > 3 else 'approve'
        feedback = sys.argv[4] if len(sys.argv) > 4 else None
        
        # action_value 完整传入（驳回/修改时含 feedback_key 和用户输入）
        action_value = None
        if len(sys.argv) > 5:
            try:
                action_value = json.loads(sys.argv[5])
            except json.JSONDecodeError:
                pass
        
        result = handle_callback(action, story_id, feedback, action_value)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    sys.exit(main())
