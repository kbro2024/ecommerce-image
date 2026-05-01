"""
Prompt templates for ecommerce-image workflow
"""
from datetime import datetime
from typing import Dict, Optional

# ============== Stage 1: Prompt Engineering

PROMPT_ENGINEERING_TEMPLATE = """你是一个专业电商产品摄影 Prompt 工程师。
用户需求：{user_input}
格式（3行）：
ANALYSIS: [1-2句产品定位和目标用户]
PROMPT: [仅视觉描述，不含品牌/文字，FLUX可理解，1-2句]
STYLE: [5个风格关键词，逗号分隔]
"""


def build_prompt_engineering(user_input: str) -> str:
    """Generate prompt engineering instruction for ling model"""
    return PROMPT_ENGINEERING_TEMPLATE.format(user_input=user_input)


def parse_llm_prompt_response(response_text: str) -> dict:
    """Parse ling model output into structured prompt parts"""
    import re

    result = {'analysis': '', 'prompt': '', 'style': ''}

    analysis_match = re.search(r'ANALYSIS:\s*(.+?)(?=PROMPT:|$)', response_text, re.DOTALL)
    prompt_match = re.search(r'PROMPT:\s*(.+?)(?=STYLE:|$)', response_text, re.DOTALL)
    style_match = re.search(r'STYLE:\s*(.+?)$', response_text, re.DOTALL)

    if analysis_match:
        result['analysis'] = analysis_match.group(1).strip()
    if prompt_match:
        result['prompt'] = prompt_match.group(1).strip()
    if style_match:
        result['style'] = style_match.group(1).strip()

    # Fallback: if parsing fails, use raw response as prompt
    if not result['prompt']:
        result['prompt'] = response_text.strip()

    return result


# ============== Stage 2: FLUX Visual Prompt Builder ==============

IMAGE_PROMPT_TEMPLATE = """你是一个专业的电商主图设计师。

## 产品信息
{product_info}

## 平台要求
{platforms}

## 设计要求
{requirements}

## 文字要求
- 价格：{price}
- 清晰展示，无乱码
- 字体大小适中，适合电商主图

## 风格要求
- 背景：{background}
- 整体风格：{style}
- 符合{platforms_str}平台的视觉规范

请生成一张专业的电商主图。
"""

def build_image_prompt(user_story: Dict, llm_prompt: str = None, style: str = None) -> str:
    """
    Build FLUX visual prompt.
    Uses ling-generated PROMPT and STYLE if available (两阶段模式),
    otherwise falls back to rule-based construction.
    """
    title = user_story.get('title', '')

    if llm_prompt:
        # Two-stage mode: use LLM-generated visual prompt directly
        style_str = f", {style}" if style else ""
        return f"{llm_prompt}{style_str}"
    else:
        # Fallback: rule-based prompt (should not be used in normal flow)
        requirements = user_story.get('requirements', [])
        requirements_text = '\n'.join(f"- {r}" for r in requirements) if requirements else "无特殊要求"
        return f"{title}, {requirements_text}"

# ============== LLM Judge Prompt ==============

JUDGE_PROMPT_TEMPLATE = """你是一个专业的电商图片审核助手。请根据User Story的要求，审核生成的图片。

## User Story 要求

### 标题
{title}

### 产品信息
{product_info}

### 平台
{platforms}

### 设计要求
{requirements}

### Out of Scope（不做）
{out_of_scope}

## 审核维度

请严格检查以下三个维度：

### 1. 内容一致性
图片中的产品品类、颜色、风格是否与要求一致？是否有明显不符合的内容？是否有物品超出out_of_scope范围？

### 2. 格式合规性
图片的尺寸、分辨率是否符合要求？格式是否为要求的PNG/JPG？

### 3. 审美基线
图片的背景、构图、色调是否在合理范围？是否有明显的AI生成瑕疵、拼接错误、模糊或变形？

## 输出格式

请严格按以下格式输出，不要包含任何额外内容：

```
RESULT: PASS | FAIL
REASON: 原因说明（如果FAIL，说明具体问题）
SUGGESTION: 修改建议（如果FAIL）
```
"""

def build_judge_prompt(user_story: Dict) -> str:
    """Build prompt for LLM Judge"""
    products = user_story.get('products', [{}])
    product = products[0] if products else {}
    product_info = '\n'.join(f"- {k}: {v}" for k, v in product.items())
    
    platforms = user_story.get('platforms', ['淘宝', '天猫', '京东'])
    platforms_str = '、'.join(platforms)
    
    requirements = user_story.get('requirements', [])
    requirements_text = '\n'.join(f"- {r}" for r in requirements) if requirements else "无特殊要求"
    
    out_of_scope = user_story.get('out_of_scope', [])
    out_of_scope_text = '\n'.join(f"- {o}" for o in out_of_scope) if out_of_scope else "无"
    
    return JUDGE_PROMPT_TEMPLATE.format(
        title=user_story.get('title', ''),
        product_info=product_info or '（未指定产品详情）',
        platforms=platforms_str,
        requirements=requirements_text,
        out_of_scope=out_of_scope_text
    )

def parse_judge_result(result_text: str) -> Dict:
    """Parse LLM Judge output"""
    import re
    
    result = {'pass': False, 'reason': '', 'suggestion': ''}
    
    # Extract RESULT — handle optional markdown '##' heading prefix
    pass_match = re.search(r'#{0,2}\s*RESULT:\s*PASS', result_text, re.IGNORECASE)
    fail_match = re.search(r'#{0,2}\s*RESULT:\s*FAIL', result_text, re.IGNORECASE)
    
    if pass_match:
        result['pass'] = True
    elif fail_match:
        result['pass'] = False
    else:
        # Default to fail if can't parse
        result['pass'] = False
        result['reason'] = '无法解析审核结果'
    
    # Extract REASON — strip optional markdown '##' heading prefix
    reason_match = re.search(r'#{0,2}\s*REASON:\s*(.+?)(?:#{0,2}\s*SUGGESTION:|$)', result_text, re.DOTALL)
    if reason_match:
        result['reason'] = reason_match.group(1).strip().lstrip('#').strip()

    # Extract SUGGESTION — strip optional markdown '##' heading prefix
    suggestion_match = re.search(r'#{0,2}\s*SUGGESTION:\s*(.+?)$', result_text, re.DOTALL)
    if suggestion_match:
        result['suggestion'] = suggestion_match.group(1).strip().lstrip('#').strip()
    
    return result
