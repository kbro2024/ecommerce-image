"""
Worker: Generate images
Supports multiple backends: mock, nvidia (FLUX.2-klein-4b), openai (gpt-image-2)
"""
import os
import sys
import json
import base64
from pathlib import Path
from datetime import datetime

# Add shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "shared"))

from prompts import build_image_prompt, build_prompt_engineering, parse_llm_prompt_response
from utils import (
    load_user_story,
    save_metadata,
    load_metadata,
    get_output_path,
)
import git_ops


# ============ CONFIGURATION ============
PROVIDER = os.getenv("IMAGE_PROVIDER", "nvidia").lower()
OPENAI_MODEL = os.getenv("IMAGE_OPENAI_MODEL", "gpt-image-2")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PROMPT_MODEL = "inclusionai/ling-2.6-1t:free"
NVIDIA_MODEL_ID = "black-forest-labs/flux.2-klein-4b"
NVIDIA_API_BASE = "https://ai.api.nvidia.com/v1/genai"
MAX_RETRIES = 3
MAX_DRAFT_VERSIONS = 20


def _get_openai_key():
    k = os.getenv("IMAGE_OPENAI_API_KEY", "")
    if k:
        return k
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("IMAGE_OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _get_openrouter_key():
    k = os.getenv("OPENROUTER_API_KEY", "")
    if k:
        return k
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _get_nvidia_key():
    k = os.getenv("NVIDIA_API_KEY", "")
    if k:
        return k
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("NVIDIA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# ============ PROVIDER INTERFACE ============

def generate(prompt: str, size: str, output_path: str) -> bytes:
    """
    Dispatch to the configured image provider.
    Returns image bytes (saved to output_path as side effect).
    """
    if PROVIDER == "mock":
        return _mock_generate(prompt, size, output_path)
    elif PROVIDER == "nvidia":
        return _call_nvidia_flux(prompt, size, output_path)
    elif PROVIDER == "openai":
        return _call_openai_gpt_image(prompt, size, output_path)
    else:
        raise ValueError(f"Unknown IMAGE_PROVIDER: {PROVIDER}")


def _mock_generate(prompt: str, size: str, output_path: str) -> bytes:
    """Create a minimal valid PNG as placeholder"""
    # 1x1 red PNG
    png_data = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
        0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x18, 0xDD,
        0x8D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
        0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
    ])
    with open(output_path, "wb") as f:
        f.write(png_data)
    print(f"  [MOCK] Created placeholder image: {output_path}")
    return png_data


def _call_nvidia_flux(prompt: str, size: str, output_path: str) -> bytes:
    """
    Call NVIDIA NIM FLUX.2-klein-4b API.
    Auth: Bearer {NVIDIA_API_KEY} — key format is nvapi-xxx
    """
    NVIDIA_API_KEY = _get_nvidia_key()
    if not NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY not set")

    import requests

    # Parse size (e.g. "1024x1024" -> 1024, 1024)
    width, height = map(int, size.split("x"))

    invoke_url = f"{NVIDIA_API_BASE}/{NVIDIA_MODEL_ID}"
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": 4,
        "seed": 0,
    }

    print(f"  [NVIDIA] Calling FLUX.2-klein-4b...")
    response = requests.post(invoke_url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()

    data = response.json()
    artifacts = data.get("artifacts", [])
    if not artifacts:
        raise RuntimeError(f"NVIDIA API returned no artifacts: {data}")

    img_b64 = artifacts[0]["base64"]
    img_bytes = base64.b64decode(img_b64)

    with open(output_path, "wb") as f:
        f.write(img_bytes)

    finish = artifacts[0].get("finishReason", "UNKNOWN")
    print(f"  [NVIDIA] Saved {len(img_bytes)} bytes, finishReason={finish}")
    return img_bytes


def _call_openai_gpt_image(prompt: str, size: str, output_path: str) -> bytes:
    """
    Call OpenAI gpt-image-2 (or compatible image gen API).
    """
    OPENAI_API_KEY = _get_openai_key()
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")

    import openai

    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    response = client.images.generate(
        model=OPENAI_MODEL,
        prompt=prompt,
        size=size,
        n=1,
        response_format="b64_json",
    )

    img_b64 = response.data[0].b64_json
    img_bytes = base64.b64decode(img_b64)

    with open(output_path, "wb") as f:
        f.write(img_bytes)

    return img_bytes


def call_prompt_llm(user_input: str) -> dict:
    """
    Call OpenRouter ling model for prompt engineering.
    Returns dict with analysis, prompt, style.
    """
    OPENROUTER_API_KEY = _get_openrouter_key()
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    import openai

    client = openai.OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

    prompt_text = build_prompt_engineering(user_input)

    response = client.chat.completions.create(
        model=PROMPT_MODEL,
        messages=[{"role": "user", "content": prompt_text}],
        max_tokens=300,
    )

    raw = response.choices[0].message.content
    parsed = parse_llm_prompt_response(raw)

    print(f"  [Prompt LLM] ANALYSIS: {parsed.get('analysis', '')}")
    print(f"  [Prompt LLM] PROMPT: {parsed.get('prompt', '')}")
    print(f"  [Prompt LLM] STYLE: {parsed.get('style', '')}")

    return parsed


# ============ CORE LOGIC ============

def generate_image(story_id: str, feedback: str = None) -> dict:
    """
    Generate image for given story.

    Args:
        story_id: User story ID
        feedback: Optional feedback from rejected/modify to incorporate

    Returns:
        dict with keys: success, draft_path, message, provider
    """
    result = {
        "success": False,
        "draft_path": None,
        "message": "",
        "retry_count": 0,
        "provider": PROVIDER,
    }

    # Load user story
    try:
        story_data = load_user_story(story_id)
        story = story_data["metadata"]
        body = story_data["body"]
    except Exception as e:
        result["message"] = f"Failed to load user story: {str(e)}"
        return result

    # Incorporate feedback if present
    if feedback:
        body = f"{body}\n\n## 修改反馈\n\n{feedback}"

    # Build prompt — Stage 1: Prompt Engineering (ling)
    # Use body (which includes feedback when present) so ling can understand the user's intent
    user_message = body
    print(f"  [Prompt LLM] Calling ling for intent understanding...")
    llm_result = call_prompt_llm(user_message)
    llm_visual_prompt = llm_result.get("prompt", "")
    llm_style = llm_result.get("style", "")
    llm_analysis = llm_result.get("analysis", "")

    # Stage 2: Build FLUX prompt
    prompt = build_image_prompt(
        {"title": story.get("title", ""), "body": body},
        llm_prompt=llm_visual_prompt,
        style=llm_style,
    )

    output_dir = get_output_path(story_id)

    for retry in range(MAX_RETRIES):
        try:
            existing_drafts = list(output_dir.glob("draft-*.png"))
            draft_num = len(existing_drafts) + 1

            # Enforce draft version cap
            if draft_num > MAX_DRAFT_VERSIONS:
                result["message"] = (
                    f"Reached max draft versions ({MAX_DRAFT_VERSIONS}). "
                    "Please review or archive existing drafts."
                )
                return result
            draft_path = str(output_dir / f"draft-{draft_num:03d}.png")

            print(f"[Generate] provider={PROVIDER} draft={draft_num}")
            image_bytes = generate(
                prompt=prompt,
                size="1024x1024",
                output_path=draft_path,
            )

            if image_bytes:
                result["success"] = True
                result["draft_path"] = draft_path
                result["message"] = f"Generated draft-{draft_num:03d}.png"

                # Update metadata
                metadata = load_metadata(story_id)
                metadata.update(
                    {
                        "status": "draft_ready",
                        "draft_path": draft_path,
                        "draft_version": draft_num,
                        "generated_at": datetime.now().isoformat(),
                        "retry_count": retry,
                        "image_provider": PROVIDER,
                        # ling prompt engineering results
                        "llm_analysis": llm_analysis,
                        "llm_visual_prompt": llm_visual_prompt,
                        "llm_style": llm_style,
                        "flux_prompt": prompt,
                    }
                )
                save_metadata(story_id, metadata)

                # Git commit
                try:
                    git_ops.add(str(output_dir))
                    git_ops.commit(f"[DRAFT] {story_id} v{draft_num} ready")
                except Exception as e:
                    print(f"Git commit warning: {e}")

                return result

        except Exception as e:
            result["retry_count"] = retry + 1
            result["message"] = f"Retry {retry + 1}/{MAX_RETRIES}: {str(e)}"
            print(f"  Generate error (retry {retry + 1}): {e}")

            if retry < MAX_RETRIES - 1:
                import time
                time.sleep(2 ** retry)

    result["message"] = f"Failed after {MAX_RETRIES} retries"
    return result


# ============ CLI ============

def main():
    """CLI entry point"""
    if len(sys.argv) < 2:
        print(f"Usage: python generate.py <story_id> [feedback]")
        print(f"IMAGE_PROVIDER={PROVIDER}")
        sys.exit(1)

    story_id = sys.argv[1]
    feedback = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Generating image for {story_id}... (provider={PROVIDER})")
    result = generate_image(story_id, feedback)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
