#!/usr/bin/env python3
"""
Mock test for ecommerce-image workflow
Mocks gpt-image-2 and GPT-4o API calls
"""
import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

# Add skills to path
sys.path.insert(0, '/home/admin/hermes/skills/ecommerce-image')

os.environ['ECOMMERCE_IMAGE_REPO'] = '/home/admin/visual-materials'
os.environ['OPENAI_API_KEY'] = 'mock-key'
os.environ['FEISHU_APP_ID'] = 'mock-app-id'
os.environ['FEISHU_APP_SECRET'] = 'mock-secret'

from shared import git_ops, prompts, utils

# ============ MOCK DATA ============

def mock_gpt_image2_generate(prompt, size, output_path):
    """Mock gpt-image-2 - creates a minimal valid PNG file"""
    # Create minimal valid PNG (1x1 red pixel)
    png_data = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT chunk
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
        0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x18, 0xDD,
        0x8D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,  # IEND
        0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82
    ])
    with open(output_path, 'wb') as f:
        f.write(png_data)
    print(f"  [MOCK] Created image: {output_path}")
    return True


def mock_gpt4o_multimodal(image_path, prompt):
    """Mock GPT-4o - always returns PASS"""
    print(f"  [MOCK] GPT-4o reviewing image: {image_path}")
    
    # Simulate some delay
    import time
    time.sleep(0.5)
    
    # Always PASS for mock
    return """RESULT: PASS
REASON: Mock review - image looks good
SUGGESTION: """


def mock_feishu_upload(image_path, token):
    """Mock Feishu image upload"""
    print(f"  [MOCK] Uploading to Feishu: {image_path}")
    return "mock-image-key-12345"


# ============ WORKFLOW STEPS ============

def step_1_parse_input(user_input):
    """Step 1: Parse user input"""
    print("\n" + "="*50)
    print("STEP 1: Parse User Input")
    print("="*50)
    print(f"Input: {user_input}")
    
    parsed = prompts.parse_user_input(user_input)
    print(f"\nParsed:")
    print(f"  Title: {parsed['title']}")
    print(f"  Products: {parsed['products']}")
    print(f"  Platforms: {parsed['platforms']}")
    
    return parsed


def step_2_create_story(parsed, user_id):
    """Step 2: Create User Story"""
    print("\n" + "="*50)
    print("STEP 2: Create User Story")
    print("="*50)
    
    story_id = utils.generate_story_id()
    print(f"Story ID: {story_id}")
    
    # Build story content
    body = f"""
# 需求描述

{parsed.get('description', '')}

## 产品信息

"""
    if parsed.get('products'):
        for p in parsed['products']:
            for k, v in p.items():
                body += f"- {k}: {v}\n"
    
    body += f"""
## 平台

{', '.join(parsed.get('platforms', []))}

## 审核记录

| 时间 | 操作 | 结果 |
|------|------|------|
| {datetime.now().isoformat()} | 创建任务 | PENDING |
"""
    
    # Save story
    utils.save_user_story(story_id, body)
    
    # Git commit
    git_ops.add(f'inbox/{story_id}.md')
    git_ops.commit(f'[NEW] {story_id} created')
    
    print(f"Saved to: inbox/{story_id}.md")
    
    # Save metadata
    utils.save_metadata(story_id, {
        'title': parsed['title'],
        'status': 'pending',
        'created_by': user_id,
        'created_at': datetime.now().isoformat()
    })
    
    return story_id


def step_3_generate(story_id, feedback=None):
    """Step 3: Generate image (mock)"""
    print("\n" + "="*50)
    print("STEP 3: Generate Image (MOCK)")
    print("="*50)
    
    if feedback:
        print(f"Feedback from previous iteration: {feedback}")
    
    # Mock gpt-image-2 call - directly create mock image
    output_dir = utils.get_output_path(story_id)
    existing_drafts = list(output_dir.glob('draft-*.png'))
    draft_num = len(existing_drafts) + 1
    draft_path = output_dir / f'draft-{draft_num:03d}.png'
    
    # Create mock PNG
    mock_gpt_image2_generate(
        prompt="mock prompt",
        size='1024x1024',
        output_path=str(draft_path)
    )
    
    # Update metadata
    metadata = utils.load_metadata(story_id)
    metadata.update({
        'status': 'draft_ready',
        'draft_path': str(draft_path),
        'draft_version': draft_num,
        'generated_at': datetime.now().isoformat()
    })
    utils.save_metadata(story_id, metadata)
    
    # Git commit
    git_ops.add(str(output_dir))
    git_ops.commit(f'[DRAFT] {story_id} v{draft_num} ready')
    
    print(f"Generated: {draft_path}")
    return draft_path


def step_4_llm_judge(story_id):
    """Step 4: LLM Judge (mock)"""
    print("\n" + "="*50)
    print("STEP 4: LLM Judge (MOCK)")
    print("="*50)
    
    # Mock GPT-4o call - just simulate
    print(f"  [MOCK] GPT-4o reviewing image...")
    import time
    time.sleep(0.5)
    
    result = {
        'pass': True,
        'reason': 'Mock review - image looks good',
        'suggestion': ''
    }
    
    # Update metadata
    metadata = utils.load_metadata(story_id)
    metadata.update({
        'judge_result': result,
        'judged_at': datetime.now().isoformat()
    })
    utils.save_metadata(story_id, metadata)
    
    # Git commit
    git_ops.add(str(utils.get_output_path(story_id)))
    git_ops.commit(f'[JUDGE] {story_id} {"PASS" if result["pass"] else "FAIL"}')
    
    print(f"Judge Result: {'PASS ✅' if result['pass'] else 'FAIL ❌'}")
    return result['pass']


def step_5_send_card(story_id, user_id):
    """Step 5: Send Feishu card (mock)"""
    print("\n" + "="*50)
    print("STEP 5: Send Feishu Card (MOCK)")
    print("="*50)
    
    metadata = utils.load_metadata(story_id)
    draft_path = metadata.get('draft_path', '')
    
    # Mock Feishu operations
    image_key = mock_feishu_upload(draft_path, "mock-token")
    print(f"  [MOCK] Sending card to user: {user_id}")
    msg_result = {"message_id": "mock-msg-12345"}
    
    # Update metadata
    metadata.update({
        'status': 'awaiting_review',
        'review_sent_at': datetime.now().isoformat(),
        'review_sent_to': user_id,
        'feishu_message_id': msg_result['message_id']
    })
    utils.save_metadata(story_id, metadata)
    
    print(f"Card sent to: {user_id}")
    print(f"Message ID: {msg_result['message_id']}")
    return msg_result


def step_6_handle_callback(story_id, action, feedback=None):
    """Step 6: Handle user callback (mock)"""
    print("\n" + "="*50)
    print(f"STEP 6: Handle Callback - {action.upper()}")
    print("="*50)
    
    if feedback:
        print(f"Feedback: {feedback}")
    
    metadata = utils.load_metadata(story_id)
    
    if action == 'approve':
        # Move to approved
        approved_dir = Path('/home/admin/visual-materials/approved') / story_id
        approved_dir.mkdir(parents=True, exist_ok=True)
        
        draft_path = metadata.get('draft_path')
        if draft_path:
            import shutil
            shutil.copy2(draft_path, approved_dir / 'final.png')
        
        metadata['status'] = 'approved'
        metadata['approved_at'] = datetime.now().isoformat()
        utils.save_metadata(story_id, metadata)
        
        git_ops.add(str(approved_dir))
        git_ops.commit(f'[APPROVE] {story_id}')
        git_ops.tag(f'approved/{story_id}/v1')
        
        print(f"✅ Approved and moved to approved/")
        return False  # No rework needed
        
    elif action in ['reject', 'modify']:
        # Save feedback and mark for rework
        utils.save_feedback(story_id, action, feedback or "No feedback provided")
        
        metadata['status'] = action
        if feedback:
            metadata[f'{action}_feedback'] = feedback
        utils.save_metadata(story_id, metadata)
        
        git_ops.add(str(Path('/home/admin/visual-materials/output') / story_id))
        git_ops.commit(f'[{action.upper()}] {story_id}')
        
        print(f"📝 {action.capitalize()} recorded, will retry generation")
        return True  # Indicates rework needed
    
    return False


# ============ MAIN ============

def main():
    print("="*60)
    print("ECOMMERCE-IMAGE WORKFLOW MOCK TEST")
    print("="*60)
    
    # Initialize repo
    print("\n[INIT] Initializing repo...")
    git_ops.init_repo()
    
    # Simulate user input
    user_input = "生成夏季连衣裙主图，SKU: DRESS-S-001，白色，¥299"
    user_id = "ou_mock_user_123"
    
    # Run workflow
    try:
        # Step 1 & 2: Parse and create story
        parsed = step_1_parse_input(user_input)
        story_id = step_2_create_story(parsed, user_id)
        
        # Step 3-5: Generate -> Judge -> Send Card
        draft_path = step_3_generate(story_id)
        judge_pass = step_4_llm_judge(story_id)
        
        if judge_pass:
            step_5_send_card(story_id, user_id)
        else:
            print("\n⚠️ LLM Judge failed, would retry...")
        
        # Step 6: Simulate user clicking "Modify" once, then "Approve"
        print("\n" + "="*60)
        print("SIMULATING USER INTERACTION")
        print("="*60)
        
        # First: User clicks "Modify"
        print("\n--- User clicks [Modify] ---")
        rework = step_6_handle_callback(story_id, 'modify', '背景改成浅蓝色渐变')
        
        if rework:
            # Retry generation
            print("\n🔄 Retrying generation with feedback...")
            step_3_generate(story_id, feedback='背景改成浅蓝色渐变')
            step_4_llm_judge(story_id)
            step_5_send_card(story_id, user_id)
        
        # Second: User clicks "Approve"
        print("\n--- User clicks [Approve] ---")
        step_6_handle_callback(story_id, 'approve')
        
        # Check final state
        print("\n" + "="*60)
        print("FINAL GIT LOG")
        print("="*60)
        os.chdir('/home/admin/visual-materials')
        log = git_ops.log(max_count=20)
        print(log)
        
        print("\n✅ Mock workflow completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
