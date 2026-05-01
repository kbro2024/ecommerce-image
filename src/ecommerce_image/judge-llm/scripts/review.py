"""
LLM Judge: Review generated images
Supports multiple backends: mock, openrouter, openai
"""
import os
import sys
import json
import base64
from pathlib import Path
from datetime import datetime
from enum import Enum

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'shared'))

from prompts import build_judge_prompt, parse_judge_result
from utils import load_user_story, load_metadata, save_metadata, get_output_path
import git_ops


class JudgeProvider(Enum):
    MOCK = "mock"
    OPENROUTER = "openrouter"
    OPENAI = "openai"
    NVIDIA = "nvidia"


# ============ CONFIGURATION ============
JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "mock").lower()
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", "")
OPENROUTER_API_KEY=os.getenv("OPENROUTER_API_KEY", "")
# NVIDIA NIM VL — uses the same NVIDIA_API_KEY as image generation
_nvidia_key = os.getenv("NVIDIA_API_KEY", "")
if not _nvidia_key:
    _env_path = Path.home() / ".hermes" / ".env"
    if _env_path.exists():
        for line in _env_path.read_text().splitlines():
            if line.startswith("NVIDIA_API_KEY="):
                _nvidia_key = line.split("=", 1)[1].strip().strip('"').strip("'")
NVIDIA_API_KEY = _nvidia_key

# Model configs
OPENAI_MODEL = os.getenv("JUDGE_OPENAI_MODEL", "gpt-4o")
OPENROUTER_MODEL = os.getenv("JUDGE_OPENROUTER_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
NVIDIA_MODEL = os.getenv("JUDGE_NVIDIA_MODEL", "google/gemma-4-31b-it")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

MAX_JUDGE_ATTEMPTS = 3


# ============ PROVIDER INTERFACE ============

def call_judge(image_path: str, prompt: str) -> str:
    """
    Dispatch to the configured judge provider.
    Returns judge raw text result.
    """
    provider = JUDGE_PROVIDER

    if provider == "mock":
        return _mock_judge(image_path, prompt)
    elif provider == "openrouter":
        return _call_openrouter(image_path, prompt)
    elif provider == "openai":
        return _call_openai(image_path, prompt)
    elif provider == "nvidia":
        return _call_nvidia(image_path, prompt)
    else:
        raise ValueError(f"Unknown JUDGE_PROVIDER: {provider}")


def _mock_judge(image_path: str, prompt: str) -> str:
    """Mock judge - always returns PASS"""
    import time
    time.sleep(0.3)
    return """RESULT: PASS
REASON: Mock review - image passes all checks
SUGGESTION: """


def _call_openrouter(image_path: str, prompt: str) -> str:
    """
    Call OpenRouter VL model for image review.
    Uses nvidia/nemotron-nano-12b-v2-vl:free by default.
    Supports image_url input via OpenAI-compatible API.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    import openai

    client = openai.OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

    # Encode image as base64
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            }
        ],
        max_tokens=1000,
    )

    return response.choices[0].message.content


def _call_openai(image_path: str, prompt: str) -> str:
    """
    Call OpenAI GPT-4o for multimodal image review.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")

    import openai

    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            }
        ],
        max_tokens=1000,
    )

    return response.choices[0].message.content


def _call_nvidia(image_path: str, prompt: str) -> str:
    """
    Call NVIDIA NIM VL model for multimodal image review.
    Uses google/gemma-4-31b-it by default (fast, ~6s, vision-capable).
    Compatible with the same NVIDIA_API_KEY used for FLUX image generation.
    """
    if not NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY not set (or not found in ~/.hermes/.env)")

    import openai

    client = openai.OpenAI(
        base_url=NVIDIA_BASE_URL,
        api_key=NVIDIA_API_KEY,
    )

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    response = client.chat.completions.create(
        model=NVIDIA_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            }
        ],
        max_tokens=1000,
    )

    return response.choices[0].message.content


# ============ CORE LOGIC ============

def judge_image(story_id: str) -> dict:
    """
    Judge generated image using configured provider.

    Args:
        story_id: User story ID

    Returns:
        dict with keys: pass, reason, suggestion, attempts, provider
    """
    result = {
        "pass": False,
        "reason": "",
        "suggestion": "",
        "attempts": 0,
        "provider": JUDGE_PROVIDER,
    }

    # Load user story
    try:
        story_data = load_user_story(story_id)
        story = story_data["metadata"]
        body = story_data["body"]
    except Exception as e:
        result["reason"] = f"Failed to load user story: {str(e)}"
        return result

    # Get latest draft
    output_dir = get_output_path(story_id)
    drafts = sorted(output_dir.glob("draft-*.png"))

    if not drafts:
        result["reason"] = "No draft image found"
        return result

    latest_draft = drafts[-1]

    # Build judge prompt
    user_story_for_judge = {
        "title": story.get("title", ""),
        "products": [],
        "platforms": story.get("platforms", "").split(",") if story.get("platforms") else [],
        "requirements": story.get("requirements", "").split("\n") if story.get("requirements") else [],
        "body": body,
    }

    judge_prompt = build_judge_prompt(user_story_for_judge)

    # Judge with retries
    for attempt in range(MAX_JUDGE_ATTEMPTS):
        result["attempts"] = attempt + 1

        try:
            judge_text = call_judge(
                image_path=str(latest_draft),
                prompt=judge_prompt,
            )

            parsed = parse_judge_result(judge_text)
            result["pass"] = parsed["pass"]
            result["reason"] = parsed["reason"]
            result["suggestion"] = parsed["suggestion"]

            # Update metadata
            metadata = load_metadata(story_id)
            metadata.update(
                {
                    "judge_attempts": attempt + 1,
                    "judge_result": parsed,
                    "judged_at": datetime.now().isoformat(),
                    "judge_provider": JUDGE_PROVIDER,
                }
            )
            save_metadata(story_id, metadata)

            if result["pass"]:
                try:
                    git_ops.add(str(output_dir))
                    git_ops.commit(f"[JUDGE] {story_id} PASS")
                except Exception as e:
                    print(f"Git commit warning: {e}")
                break
            else:
                print(f"  Judge attempt {attempt + 1} FAIL: {parsed['reason']}")

        except Exception as e:
            result["reason"] = f"Judge error: {str(e)}"

    # If all attempts failed
    if not result["pass"] and result["attempts"] >= MAX_JUDGE_ATTEMPTS:
        metadata = load_metadata(story_id)
        metadata["needs_human_intervention"] = True
        metadata["judge_final_result"] = "FAIL"
        save_metadata(story_id, metadata)

        try:
            git_ops.add(str(output_dir))
            git_ops.commit(f"[JUDGE] {story_id} FAIL - needs human intervention")
        except Exception as e:
            print(f"Git commit warning: {e}")

    return result


# ============ CLI ============

def main():
    """CLI entry point"""
    if len(sys.argv) < 2:
        print(f"Usage: python review.py <story_id>")
        print(f"JUDGE_PROVIDER={JUDGE_PROVIDER} ({'mock' if JUDGE_PROVIDER=='mock' else 'live'})")
        sys.exit(1)

    story_id = sys.argv[1]

    print(f"[Judge] story={story_id} provider={JUDGE_PROVIDER}")
    result = judge_image(story_id)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
