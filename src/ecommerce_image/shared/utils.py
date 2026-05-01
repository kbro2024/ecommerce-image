"""
Shared utilities for ecommerce-image workflow
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

REPO_ROOT = Path(os.environ.get('ECOMMERCE_IMAGE_REPO', '/home/admin/ecommerce-image'))

def load_metadata(story_id: str) -> Dict:
    """Load task metadata"""
    output_dir = REPO_ROOT / 'output' / story_id
    meta_file = output_dir / 'metadata.json'
    
    if meta_file.exists():
        with open(meta_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    return {}

def save_metadata(story_id: str, metadata: Dict):
    """Save task metadata"""
    output_dir = REPO_ROOT / 'output' / story_id
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_file = output_dir / 'metadata.json'
    
    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

def update_story_status(story_id: str, status: str, extra: Dict = None):
    """Update story status in metadata"""
    metadata = load_metadata(story_id)
    metadata['status'] = status
    metadata['updated_at'] = datetime.now().isoformat()
    if extra:
        metadata.update(extra)
    save_metadata(story_id, metadata)

def load_user_story(story_id: str) -> Dict:
    """Load user story from inbox"""
    story_file = REPO_ROOT / 'inbox' / f'{story_id}.md'
    
    if not story_file.exists():
        raise FileNotFoundError(f"User story not found: {story_id}")
    
    with open(story_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Parse frontmatter
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            body = parts[2]
            
            metadata = {}
            for line in frontmatter.strip().split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip()
            
            return {
                'metadata': metadata,
                'body': body.strip()
            }
    
    return {'metadata': {}, 'body': content}

def save_user_story(story_id: str, content: str):
    """Save user story to inbox"""
    inbox_dir = REPO_ROOT / 'inbox'
    inbox_dir.mkdir(parents=True, exist_ok=True)
    
    story_file = inbox_dir / f'{story_id}.md'
    with open(story_file, 'w', encoding='utf-8') as f:
        f.write(content)

def generate_story_id() -> str:
    """Generate unique story ID: us-YYYYMMDD-XXX"""
    date_str = datetime.now().strftime('%Y%m%d')
    
    # Count existing stories for today
    inbox_dir = REPO_ROOT / 'inbox'
    if inbox_dir.exists():
        existing = list(inbox_dir.glob(f'us-{date_str}-*.md'))
        seq = len(existing) + 1
    else:
        seq = 1
    
    return f'us-{date_str}-{seq:03d}'

def read_feedback(story_id: str) -> Optional[Dict]:
    """Read user feedback from rejected/modify interaction"""
    feedback_file = REPO_ROOT / 'output' / story_id / 'feedback.md'
    
    if not feedback_file.exists():
        return None
    
    with open(feedback_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    return {
        'content': content,
        'timestamp': datetime.now().isoformat()
    }

def save_feedback(story_id: str, feedback_type: str, feedback: str):
    """Save user feedback"""
    output_dir = REPO_ROOT / 'output' / story_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    feedback_file = output_dir / 'feedback.md'
    with open(feedback_file, 'w', encoding='utf-8') as f:
        f.write(f"## {feedback_type}\n\n")
        f.write(f"**时间**: {datetime.now().isoformat()}\n\n")
        f.write(f"**内容**:\n\n{feedback}\n")

def get_output_path(story_id: str, filename: str = None) -> Path:
    """Get output directory/file path"""
    output_dir = REPO_ROOT / 'output' / story_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if filename:
        return output_dir / filename
    return output_dir

def compress_image_for_feishu(image_path: str, max_size_kb: int = 1800) -> bytes:
    """
    Compress image for Feishu card (max 2MB).
    Returns compressed image bytes.
    """
    from PIL import Image
    import io
    
    img = Image.open(image_path)
    
    # Convert to RGB if necessary
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    
    # Resize if needed
    max_dim = 1200
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = tuple(int(d * ratio) for d in img.size)
        img = img.resize(new_size, Image.Resampling.LANCZOS)
    
    # Compress
    output = io.BytesIO()
    quality = 85
    img.save(output, format='JPEG', quality=quality, optimize=True)
    
    while output.tell() > max_size_kb * 1024 and quality > 50:
        output = io.BytesIO()
        quality -= 10
        img.save(output, format='JPEG', quality=quality, optimize=True)
    
    return output.getvalue()

def format_timestamp(dt: datetime = None) -> str:
    """Format timestamp for display"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime('%Y-%m-%d %H:%M:%S')
