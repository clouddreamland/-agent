import os

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import json
from openai import OpenAI
from tools_config import TEACHING_TOOLS
from ppt_master_bridge import generate_all_svg_previews, export_via_ppt_master  # PPT Master 专业引擎
from image_api import generate_cover
from knowledge_base import query_kb, add_to_kb
from session_db import get_history, save_message, update_session_title, save_slides_data, get_slides_data
from word_engine import build_lesson_plan_prompt, generate_lesson_plan_docx
from html5_engine import build_html5_prompt, extract_html_and_save

# ==========================================
# 1. 初始化 DashScope / OpenAI 兼容客户端
# ==========================================
MODEL_NAME = "deepseek-reasoner"

client = OpenAI(
    api_key="sk-31561bf6fae94b669c731a899c28b6ad",
    base_url="https://api.deepseek.com/v1"
)

print(f"✅ 已连接云端模型: {MODEL_NAME} (DeepSeek API)")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# 0. 全局状态 (用于 Agent 进程内上下文)
# ==========================================
_agent_state = {
    "current_slides": None,
    "ppt_file_path": None,
    "current_session_id": None  # 存储当前会话 ID，用于数据持久化
}

# ==========================================
# 2. 提示词与规范模板 (Few-Shot Prompting - 保持原样)
# ==========================================
PROMPT_CONTEXT = '''你现在是一位拥有 10 年经验的资深教学幻灯片（PPT）设计师与内容策划专家。你的任务是将用户提供的教学文本转化为高质量的 PPT 结构数据（Mini Design Spec）。

请在生成每一页的要点时，自行判断并遵循以下【高级演示文稿设计美学】：
1. **场景适应性**：PPT 是用来辅助演讲的，而不是用来当书读的。留在屏幕上的文字必须高度提炼。
2. **消除冗余（关键）**：如果标题已经是"杜甫的生平"，要点绝不能以"杜甫..."开头。
3. **视觉排版指令**：你必须为每一页指定一个 `layout`（排版模式）和一个与该页核心语义强相关的 `icon_name`（图标名），用于驱动后排版引擎。
可选的 layout 有：
  - "cover": 封面（仅限第一页）
  - "content": 普通内容页（适用于1-3个要点）
  - "image_focus": 左文右边图片形式（如果内容涉及具体实体、流程或对比）
  - "multi_column": 多列卡片排版（适用于并列特征、多个模块对比，通常需要3-4个点）
可选的 icon_name 必须从以下常用商业图标中选择（纯英文）：
bullseye, lightbulb, chart-bar, users, target, book-open, clock, checkmark, arrow-trend-up, rocket, star, shield, gem, server, globe, leaf, brain, cpu, database

=== 输出格式规范 ===
- 输出必须是一个包含 "color_scheme" 和 "slides" 的 JSON 对象。
- "color_scheme" 是全局配色方案名。你必须根据教学主题从以下四种文学专属风格中【智能选择】最契合的一款：
    - "classic_shanshui": 古典水墨/宣纸红。适用于唐诗宋词、古文观止、传统文化。
    - "modern_literary": 现代文学/极简蓝。适用于现代诗歌、散文、当代文学。
    - "vintage_journal": 复古手稿/牛皮纸棕。适用于史学研究、文摘、传记、古籍鉴赏。
    - "bamboo_study": 竹林书院/清幽绿。适用于山水田园诗、隐逸文化、自然哲学。
- "slides" 是一个数组，每个对象包含 "topic", "key_points", "layout", "icon_name" 四个 key。
- "key_points" 是字符串数组，每个元素是一条精炼的要点（每页最多 6 个）。
- 只输出纯 JSON，不要加 markdown、解释文字或代码块标记。
- 整体必须是可被 json.loads() 解析的有效 JSON。
'''

EXAMPLE_INPUT = '''
请为以下主题生成课件大纲，共2页：人工智能在医疗领域的应用与挑战
'''

EXAMPLE_ANSWER = '''
{
    "color_scheme": "mckinsey_blue",
    "slides": [
        {
            "topic": "AI 医疗应用现状",
            "key_points": [
                "加速药物研发周期，提升新药发现效率",
                "辅助医学影像诊断，识别早期病变特征",
                "智能聊天机器人帮助患者初步筛查症状"
            ],
            "layout": "cover",
            "icon_name": "target"
        },
        {
            "topic": "核心落地挑战",
            "key_points": [
                "数据质量参差不齐，标注成本高昂",
                "医疗数据高度敏感，隐私合规要求严格",
                "模型可解释性不足，临床信任度有待建立"
            ],
            "layout": "multi_column",
            "icon_name": "shield"
        }
    ]
}
'''


def summary_to_json(summary_text):
    return [
        {"role": "system", "content": PROMPT_CONTEXT},
        {"role": "user", "content": EXAMPLE_INPUT},
        {"role": "assistant", "content": EXAMPLE_ANSWER},
        {"role": "user", "content": summary_text}
    ]


# ==========================================
# 3. 底层 API 调用（替代原来的 transformers 推理）
# ==========================================
def _call_api(messages, max_tokens=1500, temperature=0.3):
    """通过 OpenAI SDK 调用 DashScope API，返回文本内容"""
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.8
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ API 调用失败: {e}")
        return None


def _call_api_with_tools(messages, tools=None, max_tokens=1024, temperature=0.2):
    """通过 OpenAI SDK 调用带工具的 API，返回完整的 response 对象"""
    if tools is None:
        tools = TEACHING_TOOLS
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=max_tokens,
            temperature=temperature
        )
        return response
    except Exception as e:
        print(f"❌ API 工具调用失败: {e}")
        return None


# ==========================================
# 4. 核心功能 1：生成初稿（API 版）
# ==========================================
def generate_ppt_json_from_local_llm(text_input):
    """通过云端 API 生成课件 JSON 初稿"""
    print("🚀 正在调用 Qwen2.5-14B 模型生成课件大纲...")
    messages = summary_to_json(text_input)

    result = _call_api(messages, max_tokens=1500, temperature=0.3)
    if result:
        print("✅ 模型返回结构化初稿！")
    return result


# ==========================================
# 5. 核心功能 2：迭代修改（API 版）
# ==========================================
MODIFY_PROMPT_CONTEXT = '''你现在是一位拥有 10 年经验的资深教学幻灯片（PPT）设计师与内容策划专家。你会收到【当前JSON数据】和【用户的修改反馈】，你的任务是根据反馈，在原有数据基础上进行修改。

=== 核心原则（绝对不能违反） ===
1. 【保留所有原有数据】：除了用户明确要求改的部分，其他内容必须原封不动保留！
2. 【输出完整JSON】：必须输出完整的JSON数组，包含原有页面+修改后的结果。
=== 结构规则 ===
1. 输出格式：必须是一个包含 "color_scheme" (配色名) 和 "slides" (数组) 的 JSON 对象。
2. 页面 Key：每页必须包含 "topic", "key_points", "layout", "icon_name" 四个key。如果新增页面，你必须指定合适的 layout 和 icon_name。

=== 页面属性赋值指南 ===
- color_scheme: "classic_shanshui" (古典水墨), "modern_literary" (现代极简), "vintage_journal" (复古手稿), "bamboo_study" (竹林清幽)
- layout (排版格式): "cover" (封面, 仅首页), "content" (常规图文), "image_focus" (左文右图), "multi_column" (多列对比/并列)
- icon_name (装饰图标): bullseye, lightbulb, chart-bar, users, target, book-open, clock, checkmark, arrow-trend-up, rocket, star, shield, gem, server, globe, leaf, brain, cpu, database

=== 常见修改场景示例 ===

示例1 - 增加一页（最常见）：
原始数据有3页，用户说"增加一页杜甫的生平"
→ 你应该输出4页的完整 JSON：保留原有 color_scheme，并为第4页分配合适的 layout 和 icon_name。

示例2 - 修改某一页：
用户说"把第2页改成关于李白的代表作"
→ 只修改第2页的 topic 和 key_points，（保持原有或更新更合适的 layout, icon_name），第1页、第3页等完全不变。

=== 输出格式要求 ===
- 输出必须是一个 JSON 对象，包含 "color_scheme" 和 "slides" (数组)。
- 只输出纯 JSON，不加 markdown 标记。
'''


def modify_ppt_json_with_local_llm(current_json_str, user_feedback):
    """通过云端 API 根据用户反馈修改课件 JSON"""
    print("\n🛠️ 正在调用模型修改课件 JSON...")

    page_count = "未知"
    try:
        _tmp = json.loads(current_json_str)
        page_count = len(_tmp)
    except Exception:
        pass

    messages = [
        {"role": "system", "content": MODIFY_PROMPT_CONTEXT},
        {"role": "user",
         "content": (
             f"[当前课件共有 {page_count} 页，以下是完整的JSON数据]:\n"
             f"{current_json_str}\n\n"
             f"[用户的修改要求]: {user_feedback}\n\n"
             f"⚠️ 请记住：必须在上面{page_count}页的基础上修改，原有的{page_count}页内容必须全部保留！\n"
             f"请直接输出修改后的完整JSON数组:"
         )}
    ]

    result = _call_api(messages, max_tokens=1500, temperature=0.2)
    if result:
        result = result.replace('```json', '').replace('```', '').strip()

        try:
            parsed = json.loads(result)
            new_count = len(parsed)
            print(f"✅ 模型修改完毕！原{page_count}页 → 新{new_count}页")
            if new_count < page_count:
                print(f"⚠️ 警告：页数减少了({page_count}→{new_count})，请确认是否为预期行为")
        except json.JSONDecodeError:
            print(f"⚠️ 返回内容无法解析为JSON")

    return result


# ==========================================
# 6. 工具执行函数（真实映射到 Python 函数）
# ==========================================

# _add_svg_previews 已被 ppt_master_bridge.generate_all_svg_previews 替代
# 新引擎通过 LLM 直接生成高质量古典中国风 SVG，不再使用硬编码 SlideDesigner


def _tool_generate_ppt(topic, pages=3):
    """generate_ppt 工具的真实执行函数（生成包含预览图的 JSON）"""
    print(f"\n[🔧 工具执行] generate_ppt → 主题: {topic}, 页数: {pages}")

    prompt_text = f"请为以下主题生成课件大纲，共{pages}页：{topic}"
    slides_json_str = generate_ppt_json_from_local_llm(prompt_text)

    if not slides_json_str:
        return f"错误：大模型生成课件内容失败，主题={topic}"

    try:
        import re as _re
        cleaned = _re.sub(r'```json\s*', '', slides_json_str)
        cleaned = _re.sub(r'```\s*', '', cleaned).strip()
        slides_data = json.loads(cleaned)
        
        # 如果模型只返回了数组，自动包装成对象
        if isinstance(slides_data, list):
            slides_data = {
                "color_scheme": "mckinsey_blue",
                "slides": slides_data
            }
            
        # 生成预览图
        slides_data = generate_all_svg_previews(client, MODEL_NAME, slides_data)
        
    except json.JSONDecodeError:
        return f"错误：JSON解析失败。原始输出: {slides_json_str[:200]}"

    _agent_state["current_slides"] = slides_data
    _agent_state["ppt_file_path"] = None

    # 立即持久化 PPT 数据到数据库
    session_id = _agent_state.get("current_session_id")
    if session_id:
        try:
            save_slides_data(session_id, slides_data)
            print(f"💾 已立即保存 {len(slides_data.get('slides', []))} 页 PPT 数据到会话 {session_id[:8]}...")
        except Exception as e:
            print(f"⚠️ 保存 PPT 数据失败: {e}")

    slides = slides_data.get("slides", [])
    outline_preview = "\n".join(
        [f"  第{i+1}页: {s.get('topic', '未命名')} ({len(s.get('key_points', []))}个要点)" for i, s in enumerate(slides)]
    )

    return (f"✅ 已成功生成「{topic}」的课件大纲！共 {len(slides)} 页。\n"
            f"🎨 配色方案: {slides_data.get('color_scheme', '默认')}\n"
            f"\n📋 大纲预览:\n{outline_preview}\n"
            f"\n💡 你可以右侧直接查看视觉预览图，或通过对话调整内容与风格。确认无误后点击「导出PPT」。")


def _extract_json_array_from_messy_text(text):
    """从混乱的模型输出中尽力提取JSON数组"""
    import re as _re

    text = text.replace('```json', '').replace('```', '').strip()

    pattern = r'\[\s*\{'
    match = _re.search(pattern, text)
    if not match:
        return None, "未找到JSON数组起始标记"

    start = match.start()

    depth = 0
    for i in range(start, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                json_str = text[start:i+1]
                try:
                    data = json.loads(json_str)
                    return data, None
                except json.JSONDecodeError:
                    continue

    return None, "无法提取完整JSON数组"


def _detect_user_intent(feedback):
    """检测用户修改意图: add / edit / delete / reorder / unknown"""
    fb = feedback.lower()
    add_keywords = ['增加', '添加', '加一页', '新增', '补充', '再加一页', '多加',
                    '加一页关于', '增加一页', '添加一页', '再加', 'append', 'add']
    delete_keywords = ['删除', '去掉', '删掉', '移除', '不要', '去掉第', '删除第',
                       'delete', 'remove']
    modify_keywords = ['改成', '改为', '修改成', '修改为', '把.*改成', '把.*改为',
                       '替换', '换成', 'edit', 'change', 'modify']
    reorder_keywords = ['调换', '交换', '换个顺序', '移到', '移至', '调序',
                        'swap', 'reorder', 'move']

    for kw in add_keywords:
        if kw in fb:
            return 'add'
    for kw in delete_keywords:
        if kw in fb:
            return 'delete'
    for kw in modify_keywords:
        if kw in fb:
            return 'modify'
    for kw in reorder_keywords:
        if kw in fb:
            return 'reorder'
    return 'unknown'


def _parse_page_numbers(feedback, max_pages):
    """从用户反馈中解析出涉及的页码（返回 0-based index 列表）"""
    import re as _re
    indices = set()

    chinese_nums = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

    for cn, num in chinese_nums.items():
        if f'第{cn}页' in feedback or f'第{cn}' in feedback:
            idx = num - 1
            if 0 <= idx < max_pages:
                indices.add(idx)

    arabic_matches = _re.findall(r'第(\d+)页', feedback)
    for m in arabic_matches:
        idx = int(m) - 1
        if 0 <= idx < max_pages:
            indices.add(idx)

    standalone = _re.findall(r'(?<!\w)(\d+)(?!\w)页', feedback)
    for m in standalone:
        idx = int(m) - 1
        if 0 <= idx < max_pages:
            indices.add(idx)

    if '最后一页' in feedback or '最后' in feedback:
        indices.add(max_pages - 1)
    if '第一页' in feedback:
        indices.add(0)

    return sorted(indices)


def _safe_execute_intent(original, intent, feedback):
    """用代码直接执行用户意图（不依赖模型返回的正确性）"""
    orig_count = len(original)

    if intent == 'delete':
        target_indices = _parse_page_numbers(feedback, orig_count)
        if not target_indices:
            print(f"  ⚠️ 无法从反馈中解析出要删除的页码: {feedback}")
            return list(original)

        result = [slide for i, slide in enumerate(original) if i not in target_indices]
        deleted_topics = [original[i].get('topic', f'第{i+1}页') for i in target_indices]
        print(f"  🔧 代码级删除: 移除了第{[i+1 for i in target_indices]}页 ({deleted_topics})")
        print(f"  ✅ 删除完成: {orig_count}页 → {len(result)}页")
        return result

    if intent == 'reorder':
        indices = _parse_page_numbers(feedback, orig_count)
        if len(indices) >= 2:
            i, j = indices[0], indices[1]
            if 0 <= i < orig_count and 0 <= j < orig_count:
                result = list(original)
                result[i], result[j] = result[j], result[i]
                print(f"  🔧 代码级交换: 第{i+1}页 ↔ 第{j+1}页")
                print(f"  ✅ 交换完成")
                return result
            else:
                print(f"  ⚠️ 交换越界: {i}, {j} (越界, 总长度 {orig_count})")

        print(f"  ⚠️ 无法从反馈中解析出要交换的页码: {feedback}")
        return list(original)

    return list(original)


def _safe_merge_slides(original, new_data, intent, feedback):
    """
    智能合并：当模型返回结果不理想时，用代码逻辑兜底

    核心策略：
    - delete/reorder: 直接用代码执行，完全绕过模型
    - add: 原数据 + 模型新内容合并去重
    - modify: 尝试智能替换
    """
    orig_count = len(original)
    new_count = len(new_data) if new_data else 0

    print(f"  📊 兜底合并: 原始{orig_count}页 → 模型返回{new_count}页 → 意图={intent}")

    if intent == 'delete':
        if new_count >= orig_count:
            print(f"  ⚠️ 用户要求「删除」但模型没删({orig_count}→{new_count})，启用代码级删除")
            return _safe_execute_intent(original, intent, feedback)
        code_result = _safe_execute_intent(original, intent, feedback)
        if abs(len(code_result) - new_count) <= 1:
            return new_data
        print(f"  ⚠️ 模型结果与代码执行不一致，使用代码执行结果")
        return code_result

    if intent == 'reorder':
        print(f"  ⚠️ 「调序」操作：使用代码级执行确保正确性")
        return _safe_execute_intent(original, intent, feedback)

    if intent == 'add':
        if new_count < orig_count:
            print(f"  🔧 检测到「增加」但模型丢数据，自动追加...")
            merged = list(original)
            for slide in new_data:
                slide_topic = slide.get('topic', '').strip()
                is_duplicate = any(
                    s.get('topic', '').strip() == slide_topic or slide_topic in s.get('topic', '')
                    for s in merged
                )
                if not is_duplicate and slide.get('key_points'):
                    merged.append(slide)
            print(f"  ✅ 合并完成: {orig_count}页 → {len(merged)}页")
            return merged
        return new_data if new_data else list(original)

    if intent == 'modify':
        target_indices = _parse_page_numbers(feedback, orig_count)
        if new_count == orig_count and new_data:
            return new_data
        elif new_count == 1 and orig_count > 1 and target_indices:
            merged = list(original)
            for idx in target_indices:
                if idx < len(merged) and new_data[0].get('key_points'):
                    merged[idx] = {
                        'topic': new_data[0].get('topic', merged[idx].get('topic', '')),
                        'key_points': new_data[0].get('key_points', merged[idx].get('key_points', []))
                    }
            print(f"  ✅ 应用完成: 目标第{[i+1 for i in target_indices]}页已更新")
            return merged
        elif new_count < orig_count:
            merged = list(original)
            for i, new_slide in enumerate(new_data):
                if i < len(merged) and new_slide.get('key_points') and len(new_slide['key_points']) > 0:
                    merged[i] = new_slide
            return merged
        return new_data if new_data else list(original)

    print(f"  ℹ️ 意图={intent}(未知)，使用模型原始返回")
    return new_data if new_data else list(original)


def _tool_modify_ppt(feedback):
    """modify_ppt 工具的真实执行函数（仅修改JSON，含智能兜底机制）"""
    print(f"\n[🔧 工具执行] modify_ppt → 反馈: {feedback}")

    if not _agent_state.get("current_slides"):
        return "错误：当前没有可修改的课件，请先生成课件。"

    original_full_data = _agent_state["current_slides"]
    # 兼容旧版本或确保获取 slides 数组
    original_slides = original_full_data.get("slides") if isinstance(original_full_data, dict) else original_full_data
    original_color = original_full_data.get("color_scheme", "mckinsey_blue") if isinstance(original_full_data, dict) else "mckinsey_blue"
    
    orig_count = len(original_slides)
    intent = _detect_user_intent(feedback)

    # 🚀 性能与稳定性起飞：针对调序和删除操作，彻底绕过大模型，纯代码极速执行！
    if intent in ['delete', 'reorder']:
        print(f"  ⚡ 意图检测为 {intent}，直接触发极速代码级修改（跳过大模型）")
        final_slides = _safe_execute_intent(original_slides, intent, feedback)
        
        final_full_data = {
            "color_scheme": original_color,
            "slides": final_slides
        }
        # delete/reorder 操作不改变已有 SVG，无需重新生成（极速生效）
        
        _agent_state["current_slides"] = final_full_data
        _agent_state["ppt_file_path"] = None

        session_id = _agent_state.get("current_session_id")
        if session_id:
            try:
                save_slides_data(session_id, final_full_data)
                print(f"💾 已极速保存修改后的 {len(final_slides)} 页 PPT 数据到会话 {session_id[:8]}...")
            except Exception as e:
                print(f"⚠️ 保存修改后的 PPT 数据失败: {e}")
                
        return f"✅ 已根据你的意见完成修改（极速生效）！\n修改内容: {feedback}\n\n💡 右侧预览图已同步更新，确认无误后点击「导出PPT」。"

    # 清洗：移除极其占用 Token 数量的 preview_svg 字段，防止污染大模型上线
    clean_original_slides = []
    for s in original_slides:
        s_copy = dict(s)
        s_copy.pop("preview_svg", None)
        clean_original_slides.append(s_copy)
        
    clean_full_data = {
        "color_scheme": original_color,
        "slides": clean_original_slides
    }

    current_json_str = json.dumps(clean_full_data, ensure_ascii=False, indent=2)
    updated_json_str = modify_ppt_json_with_local_llm(current_json_str, feedback)

    if not updated_json_str:
        return f"错误：大模型修改失败。反馈内容: {feedback}"

    import re as _re
    cleaned = _re.sub(r'```json\s*', '', updated_json_str)
    cleaned = _re.sub(r'```\s*', '', cleaned).strip()

    updated_data = None
    parse_error = None

    try:
        updated_data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        parse_error = str(e)
        print(f"  ⚠️ 标准JSON解析失败: {parse_error}")
        print(f"  🔄 尝试从混乱输出中提取JSON数组...")
        extracted, extract_err = _extract_json_array_from_messy_text(cleaned)
        if extracted:
            updated_data = extracted
            print(f"  ✅ 成功提取JSON数组！共{len(updated_data)}页")
        else:
            print(f"  ❌ 提取也失败了: {extract_err}")

    intent = _detect_user_intent(feedback)

    if updated_data is not None:
        if isinstance(updated_data, dict) and 'slides' in updated_data:
            next_color = updated_data.get('color_scheme', original_color)
            raw_new_slides = updated_data['slides']
        else:
            next_color = original_color
            raw_new_slides = updated_data
            
        new_count = len(raw_new_slides)
        print(f"  📊 意图检测: {intent} | 原始{orig_count}页 → 模型返回{new_count}页 | 颜色: {next_color}")
        final_slides = _safe_merge_slides(original_slides, raw_new_slides, intent, feedback)
        
        final_full_data = {
            "color_scheme": next_color,
            "slides": final_slides
        }
        
        # 重新生成 SVG 预览（通过 LLM 逐页生成高质量 SVG）
        final_full_data = generate_all_svg_previews(client, MODEL_NAME, final_full_data)
        
        _agent_state["current_slides"] = final_full_data
        _agent_state["ppt_file_path"] = None

        # 立即持久化修改后的 PPT 数据到数据库（替换旧数据）
        session_id = _agent_state.get("current_session_id")
        if session_id:
            try:
                save_slides_data(session_id, final_full_data)
                print(f"💾 已立即保存修改后的 {len(final_slides)} 页 PPT 数据到会话 {session_id[:8]}...")
            except Exception as e:
                print(f"⚠️ 保存修改后的 PPT 数据失败: {e}")

        outline_preview = "\n".join([
            f"  第{i+1}页: {s.get('topic', '未命名')} ({len(s.get('key_points', []))}个要点)"
            for i, s in enumerate(final_slides)
        ])

        return (
            f"✅ 已根据你的意见完成修改！\n"
            f"修改内容: {feedback}\n"
            f"课件从 {orig_count} 页更新为 {len(final_slides)} 页。\n"
            f"🎨 配色方案: {final_full_data.get('color_scheme', '默认')}\n"
            f"\n📋 更新后的大纲:\n{outline_preview}\n"
            f"\n💡 右侧预览图已同步更新，确认无误后点击「导出PPT」。"
        )

    fallback_msg = (
        f"⚠️ 大模型返回的内容格式异常，已自动为你尝试处理。\n"
        f"原反馈: {feedback}\n\n"
        f"你可以换个说法再试试，比如：\n"
        f"- \"在最后加一页关于xxx\"\n"
        f"- \"把第2页的主题改成xxx\""
    )
    return fallback_msg


def _tool_export_ppt():
    """export_ppt 工具的真实执行函数 - 使用 PPT Master 专业管线导出"""
    print(f"\n[🔧 工具执行] export_ppt → 开始通过 PPT Master 管线生成最终PPT文件")

    if not _agent_state.get("current_slides"):
        return "错误：当前没有可导出的课件，请先生成课件。"

    full_data = _agent_state["current_slides"]
    slides = full_data.get("slides") if isinstance(full_data, dict) else full_data

    output_file = os.path.join(os.path.dirname(CURRENT_DIR), "ppts", "AI_Auto_Generated_Courseware.pptx")

    print(f"  📦 正在通过 PPT Master 管线导出 {len(slides)} 页课件...")
    result = export_via_ppt_master(full_data, output_file)

    _agent_state["ppt_file_path"] = output_file

    if result and os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        size_str = f"{file_size / 1024:.1f} KB" if file_size < 1024 * 1024 else f"{file_size / (1024*1024):.1f} MB"
        first_topic = slides[0].get('topic', '未命名') if slides else '未命名'
        return (f"🎉 您的PPT课件《{first_topic}》已经准备好啦！\n\n"
                f"您可以点击以下链接直接下载：\n"
                f"📥 **[下载 PPT 课件 (AI_Auto_Generated_Courseware.pptx)](http://127.0.0.1:8000/downloads/AI_Auto_Generated_Courseware.pptx)**\n\n"
                f"文件大小: {size_str}，共 {len(slides)} 页。")
    else:
        return "⚠️ PPT导出过程中出现问题，请稍后重试。"


def _tool_search_textbook(query):
    """search_textbook 工具的真实执行函数（RAG 知识库检索）"""
    print(f"\n[🔧 工具执行] search_textbook → 查询: {query}")

    results = query_kb(query, n_results=2)

    if not results:
        return (f"在教材知识库中未找到与「{query}」相关的知识点。\n"
                f"建议：你可以基于通用知识回答学生的问题。")

    combined = "\n\n".join([f"[知识库片段 {i+1}] {r}" for i, r in enumerate(results)])
    return (f"从教材知识库中检索到以下关于「{query}」的权威内容：\n"
            f"{combined}\n\n"
            f"请基于以上内容为学生解答问题。")


def _tool_generate_word_lesson_plan(topic):
    """generate_word_lesson_plan 工具的真实执行函数（生成 Word 教案文档）"""
    import re as _re
    print(f"\n[🔧 工具执行] generate_word_lesson_plan → 主题: {topic}")

    # 1. 通过 LLM 生成结构化教案 JSON
    messages = build_lesson_plan_prompt(topic)
    result = _call_api(messages, max_tokens=3000, temperature=0.4)

    if not result:
        return f"错误：大模型生成教案内容失败，主题={topic}"

    # 2. 解析 JSON
    try:
        cleaned = _re.sub(r'```json\s*', '', result)
        cleaned = _re.sub(r'```\s*', '', cleaned).strip()
        lesson_data = json.loads(cleaned)
    except json.JSONDecodeError:
        return f"错误：教案 JSON 解析失败。原始输出: {result[:300]}"

    # 3. 渲染 Word 文档
    try:
        output_path = generate_lesson_plan_docx(lesson_data)
    except Exception as e:
        print(f"  ❌ Word 渲染异常: {e}")
        return f"错误：Word 文档生成失败: {str(e)}"

    filename = os.path.basename(output_path)
    file_size = os.path.getsize(output_path)
    size_str = f"{file_size / 1024:.1f} KB"

    title = lesson_data.get('title', topic)
    sections = []
    if lesson_data.get('teaching_objectives'):
        sections.append(f"教学目标 ({len(lesson_data['teaching_objectives'])} 条)")
    if lesson_data.get('teaching_process'):
        sections.append(f"教学过程 ({len(lesson_data['teaching_process'])} 个阶段)")
    if lesson_data.get('teaching_methods'):
        sections.append(f"教学方法 ({len(lesson_data['teaching_methods'])} 种)")
    if lesson_data.get('activity_design'):
        sections.append(f"课堂活动 ({len(lesson_data['activity_design'])} 个)")
    if lesson_data.get('homework'):
        sections.append(f"课后作业 ({len(lesson_data['homework'])} 项)")

    sections_summary = "、".join(sections) if sections else "五大教学模块"

    return (
        f"🎉 教案《{title}》已生成完毕！\n\n"
        f"📄 文档包含：{sections_summary}\n"
        f"📦 文件大小：{size_str}\n\n"
        f"📥 **[点击下载 Word 教案文档 ({filename})](http://127.0.0.1:8000/downloads/{filename})**"
    )


def _tool_generate_html5_interactive(topic):
    """generate_html5_interactive 工具的真实执行函数（生成 HTML5 互动小游戏）"""
    print(f"\n[🔧 工具执行] generate_html5_interactive → 主题: {topic}")

    # 1. 构建 Prompt 并调用大模型生成 HTML 代码
    messages = build_html5_prompt(topic)
    
    # 使用更大的 token 限制，因为完整的 HTML 游戏代码量很大
    # deepseek-reasoner 不支持 temperature/top_p，所以使用独立调用
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            max_tokens=8192
        )
        result = response.choices[0].message.content
        
        # 调试日志：查看模型实际返回了什么
        if result:
            print(f"  📝 模型返回内容长度: {len(result)} 字符")
            print(f"  📝 模型返回前200字符: {result[:200]}...")
        else:
            print(f"  ⚠️ 模型 content 字段为空！")
            # 检查是否有 reasoning_content（思考型模型的思考链）
            reasoning = getattr(response.choices[0].message, 'reasoning_content', None)
            if reasoning:
                print(f"  📝 模型 reasoning_content 长度: {len(reasoning)} 字符")
                print(f"  📝 reasoning 中是否包含 HTML: {'<html' in reasoning.lower()}")
                # 如果思考链里有完整的 HTML 代码，从那里提取
                if '<html' in reasoning.lower() and '</html>' in reasoning.lower():
                    print(f"  🔄 从 reasoning_content 中提取 HTML 代码...")
                    result = reasoning
    except Exception as e:
        print(f"  ❌ API 调用失败: {e}")
        return f"错误：大模型生成互动内容失败 - {str(e)}"

    if not result:
        return f"错误：大模型生成互动内容失败，主题={topic}"

    # 2. 提取 HTML 代码并保存为文件
    file_path, filename = extract_html_and_save(result, topic)

    if file_path is None:
        # filename 此时包含错误信息
        return f"错误：HTML5 代码提取失败 - {filename}"

    file_size = os.path.getsize(file_path)
    size_str = f"{file_size / 1024:.1f} KB"

    return (
        f"🎮 互动小游戏《{topic}》已生成完毕！\n\n"
        f"这是一个可以在浏览器中直接运行的 HTML5 互动页面，包含精美的动画效果和趣味互动机制。\n\n"
        f"📦 文件大小：{size_str}\n\n"
        f"📥 **[点击下载 HTML5 互动小游戏 ({filename})](http://127.0.0.1:8000/downloads/{filename})**\n\n"
        f"💡 下载后双击即可在浏览器中打开运行，无需任何额外软件！"
    )


AVAILABLE_TOOLS = {
    "generate_ppt": _tool_generate_ppt,
    "modify_ppt": _tool_modify_ppt,
    "export_ppt": _tool_export_ppt,
    "search_textbook": _tool_search_textbook,
    "generate_word_lesson_plan": _tool_generate_word_lesson_plan,
    "generate_html5_interactive": _tool_generate_html5_interactive
}


# ==========================================
# 7. Agent 主循环（标准 OpenAI Function Calling 双向闭环）
# ==========================================

AGENT_SYSTEM_PROMPT = """你是一个AI教学助手老师。你可以使用以下工具来帮助学生：
- generate_ppt: 根据主题和页数【从零开始生成】全新的PPT课件
- modify_ppt: 【在已有课件基础上】修改内容（增删页面、修改文字、更换风格）
- export_ppt: 导出最终PPT文件
- search_textbook: 从教材知识库检索权威知识点答案
- generate_word_lesson_plan: 生成Word格式的详细教案文档（含教学目标、过程、方法、活动、作业）
- generate_html5_interactive: 生成HTML5互动小游戏或动画演示（可在浏览器中运行的趣味互动内容）

=== 最高优先级：角色约束 ===
❗ 你是「老师/助手」，永远以教师身份向学生汇报和说明。
❗ 绝对禁止模拟「学生」的角色或语气。不要说「我想…」「太棒了！帮我…」等仿学生语句。
❗ 工具执行完成后，用简洁教师语气汇报结果，如：「已帮您更换为现代文学风格，请在右侧查看。」

=== 关键规则（必须严格遵守） ===
1. 【generate_ppt】：仅当用户【第一次】要求做PPT/幻灯片/演示文稿时调用。
2. 【generate_word_lesson_plan】：当用户要求生成「教案」「教学设计」「教学方案」「教案文档」时调用。
   ⚠️ 教案 ≠ PPT！教案是Word文档，PPT是演示文稿，二者工具不同！
3. 【generate_html5_interactive】：当用户要求生成「小游戏」「互动游戏」「趣味练习」「动画演示」「知识闯关」「课堂互动活动」或提到「HTML5」「互动内容」时调用。
   ⚠️ 互动小游戏 ≠ PPT！小游戏是HTML5网页，PPT是演示文稿，二者工具不同！
4. 【modify_ppt】：只要之前已生成课件，用户的任何调整都调用 modify_ppt：
   增加/删除/修改/换风格/调整顺序 → 全部 modify_ppt
5. 当学生确认要导出时，调用 export_ppt
6. 学术知识点优先调用 search_textbook
7. 纯文字需求直接回答

⚠️ 用户已有课件但说'帮我做个杜甫的生平' → 必须 modify_ppt，绝不重新生成！

重要：工具执行完成后，用自然语言向学生汇报结果。你是老师，不是学生。"""


def chat_with_agent(user_message, session_id=None, max_rounds=3):
    """
    Agent 双向闭环主循环（OpenAI Function Calling 规范）

    流程（严格遵循 OpenAI 标准）：
      第一轮请求：注入 System Prompt → 调用带 tools 的 API → 解析 tool_calls
      工具执行：遍历 tool_calls → 通过 AVAILABLE_TOOLS 映射执行本地函数 → 构建 role:"tool" 消息
      第二轮请求：携带工具结果的 messages 再次请求 → 获取最终自然语言总结

    参数:
      user_message: 用户消息
      session_id: 会话ID，如果提供则从数据库加载历史消息
      max_rounds: 最大工具调用轮次

    返回值:
      dict {
        "reply": str,
        "slides_data": list|None,
        "status": str,
        "file_path": str|None
      }
    """
    print(f"\n{'='*60}")
    print(f"  👨‍🎓 学生: {user_message}")
    print(f"{'='*60}")

    # 保存当前会话 ID 到全局状态（用于数据持久化）
    _agent_state["current_session_id"] = session_id
    
    # 强制状态同步：如果内存中没有当前幻灯片，从数据库回拉
    if session_id and not _agent_state.get("current_slides"):
        db_data = get_slides_data(session_id)
        if db_data:
            _agent_state["current_slides"] = db_data
            print(f"  🔄 从数据库回拉会话 {session_id[:8]}... 的 PPT 数据")

    # ===== 构建带历史记忆的 messages =====
    messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]

    if session_id:
        # 从数据库加载历史消息（最近20条）
        history = get_history(session_id, limit=20)
        if history:
            messages.extend(history)
            print(f"  📚 已加载 {len(history)} 条历史消息")

        # 保存当前用户消息到数据库
        save_message(session_id, "user", user_message)

        # 如果是第一条消息，自动生成会话标题
        if not history:
            title = user_message[:20] + ("..." if len(user_message) > 20 else "")
            update_session_title(session_id, title)
            print(f"  📝 会话标题设为: {title}")

    messages.append({"role": "user", "content": user_message})

    called_tools = []

    for round_num in range(1, max_rounds + 1):
        print(f"\n--- 第 {round_num} 回合 ---")

        response = _call_api_with_tools(
            messages, tools=TEACHING_TOOLS, max_tokens=2048, temperature=0.2
        )

        if response is None:
            print("❌ API 无响应，终止 Agent 循环")
            return _build_agent_response("抱歉，服务暂时不可用，请稍后再试。", called_tools, session_id)

        assistant_message = response.choices[0].message
        raw_content = assistant_message.content or ""
        print(f"🤖 模型原始输出: {raw_content[:300]}...")

        messages.append(assistant_message)

        if assistant_message.tool_calls:
            print(f"  📦 Agent 决定调用 {len(assistant_message.tool_calls)} 个工具")

            for tool_call in assistant_message.tool_calls:
                func_name = tool_call.function.name
                func_args_raw = tool_call.function.arguments
                called_tools.append(func_name)

                try:
                    func_args = json.loads(func_args_raw)
                except json.JSONDecodeError:
                    func_args = {}
                    print(f"  ⚠️ 参数JSON解析失败: {func_args_raw}")

                print(f"  📦 工具: {func_name}")
                print(f"  📋 参数: {json.dumps(func_args, ensure_ascii=False)}")

                if func_name not in AVAILABLE_TOOLS:
                    tool_result = f"错误: 未知工具 '{func_name}'"
                else:
                    try:
                        exec_func = AVAILABLE_TOOLS[func_name]
                        tool_result = exec_func(**func_args)
                    except Exception as e:
                        tool_result = f"工具执行异常: {str(e)}"
                        print(f"  ❌ 执行异常: {e}")

                print(f"  ✅ 工具执行结果: {str(tool_result)[:200]}...")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": str(tool_result)
                })

            print(f"  🔄 正在将结果反馈给模型，等待最终回复...")
            continue

        else:
            final_answer = raw_content or "(模型无文字输出)"
            print(f"\n{'='*60}")
            print(f"  🤖 老师最终回复:")
            print(f"  {final_answer}")
            print(f"{'='*60}\n")

            # 保存助手回复到数据库
            if session_id:
                save_message(session_id, "assistant", final_answer)

            return _build_agent_response(final_answer, called_tools, session_id)

    fallback_response = _call_api_with_tools(
        messages, tools=TEACHING_TOOLS, max_tokens=512, temperature=0.3
    )
    if fallback_response:
        fallback = fallback_response.choices[0].message.content or "抱歉，无法生成回复。"
    else:
        fallback = "抱歉，服务暂时不可用。"

    print(f"\n{'='*60}")
    print(f"  🤖 老师最终回复 (兜底):")
    print(f"  {fallback}")
    print(f"{'='*60}\n")

    # 保存兜底回复到数据库
    if session_id:
        save_message(session_id, "assistant", fallback)

    return _build_agent_response(fallback, called_tools, session_id)


def _build_agent_response(reply_text, called_tools=None, session_id=None):
    """根据当前状态构建结构化返回值"""
    if called_tools is None:
        called_tools = []

    slides = _agent_state.get("current_slides")
    file_path = _agent_state.get("ppt_file_path")

    if "generate_ppt" in called_tools:
        status = "generated"
    elif "modify_ppt" in called_tools:
        status = "modified"
    elif "export_ppt" in called_tools:
        status = "exported"
    elif "generate_word_lesson_plan" in called_tools:
        status = "lesson_plan_generated"
    elif "generate_html5_interactive" in called_tools:
        status = "html5_generated"
    elif slides:
        status = "generated"
    else:
        status = "idle"

    # 自动持久化 PPT 数据到数据库（如果存在会话 ID）
    if session_id and slides and status != "idle":
        try:
            save_slides_data(session_id, slides)
            print(f"💾 已自动保存 PPT 数据到会话 {session_id[:8]}...")
        except Exception as e:
            print(f"⚠️ 保存 PPT 数据失败: {e}")

    return {
        "reply": reply_text,
        "slides_data": slides,
        "status": status,
        "file_path": file_path
    }


# ==========================================
# 8. 测试运行（Agent 双向闭环验证）
# ==========================================
if __name__ == "__main__":
    print("\n" + "█" * 60)
    print("  🚀 AI 教学智能体 - Agent 双向闭环测试 (DashScope API)")
    print("█" * 60)

    print("\n>>> 测试 A: 闲聊（不触发工具）")
    chat_with_agent("老师好，今天天气怎么样？")

    print("\n" + "─" * 60)

    print("\n>>> 测试 B: 触发 PPT 生成工具")
    chat_with_agent("帮我生成一个关于光合作用的PPT，需要5页")

    print("\n" + "─" * 60)

    print("\n>>> 测试 C: 触发修改工具（在已有PPT基础上）")
    chat_with_agent("增加一页关于实验方法的内容")

    print("\n" + "█" * 60)
    print("  ✅ 所有测试完成！")
    print("█" * 60)
