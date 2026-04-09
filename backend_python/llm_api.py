import os

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import json
from openai import OpenAI
from tools_config import TEACHING_TOOLS
from ppt_engine import export_to_ppt
from image_api import generate_cover
from knowledge_base import query_kb, add_to_kb
from session_db import get_history, save_message, update_session_title, save_slides_data, get_slides_data

# ==========================================
# 1. 初始化 DashScope / OpenAI 兼容客户端
# ==========================================
MODEL_NAME = "qwen2.5-14b-instruct"

client = OpenAI(
    api_key="sk-5fdd25047c7e48e3a771c43ee5156f79",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

print(f"✅ 已连接云端模型: {MODEL_NAME} (DashScope API)")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# 2. 提示词与规范模板 (Few-Shot Prompting - 保持原样)
# ==========================================
PROMPT_CONTEXT = '''你现在是一位拥有 10 年经验的资深教学幻灯片（PPT）设计师与内容策划专家。你的任务是将用户提供的教学文本转化为高质量的 PPT 结构数据。

请在生成每一页的要点时，自行判断并遵循以下【高级演示文稿设计美学】：
1. **场景适应性**：PPT 是用来辅助演讲的，而不是用来当书读的。请确保留在屏幕上的文字是高度提炼的精华。
2. **消除冗余（关键）**：人类在做 PPT 时，如果标题已经是"杜甫的生平"，下面的要点绝不会愚蠢地每条都以"杜甫..."开头。请像人类专家一样，自动根据上下文省略不必要的重复主语或客套话。
3. **风格动态调整**：根据学科不同自动调整文风。如果是人文学科（如历史、文学），请使用精炼的短语或四字词语；如果是理工科（如数学、物理），请保留严谨的公式或概念陈述。
4. **信息层级感**：每个要点应该是一个独立且核心的信息块，做到字数精简，重点一目了然。

=== 输出格式规范 ===
- 输出必须是一个 JSON 数组，每个对象包含 "topic" 和 "key_points" 两个 key
- "key_points" 是字符串数组，每个元素是一条精炼的要点
- 每个主题下最多 6 个要点，超出时自行取舍最重要的
- 只输出纯 JSON，不要加 markdown、解释文字或代码块标记
- 整体必须是可被 json.loads() 解析的有效 JSON
'''

EXAMPLE_INPUT = '''
请为以下主题生成课件大纲，共2页：人工智能在医疗领域的应用与挑战
'''

EXAMPLE_ANSWER = '''
[
    {
        "topic": "AI 医疗应用现状",
        "key_points": [
            "加速药物研发周期，提升新药发现效率",
            "辅助医学影像诊断，识别早期病变特征",
            "智能聊天机器人帮助患者初步筛查症状"
        ]
    },
    {
        "topic": "落地挑战",
        "key_points": [
            "数据质量参差不齐，标注成本高昂",
            "医疗数据高度敏感，隐私合规要求严格",
            "模型可解释性不足，临床信任度有待建立"
        ]
    }
]
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
2. 【输出完整JSON】：必须输出完整的JSON数组，包含原有页面+修改后的结果
3. 【结构不变】：每项只有 "topic" 和 "key_points" 两个key

=== 高级演示文稿设计美学（修改时同样适用） ===
- **消除冗余**：标题已说明主题时，要点中自动省略重复主语
- **风格一致**：新增或修改的内容，文风要与已有内容保持统一
- **精炼表达**：每条要点是独立的信息块，字数精简、重点突出

=== 常见修改场景示例 ===

示例1 - 增加一页（最常见）：
原始数据有3页，用户说"增加一页杜甫的生平"
→ 你应该输出4页：原来的3页全部保留 + 新增1页"杜甫的生平"
→ 绝对不能只输出1页！

示例2 - 修改某一页：
用户说"把第2页改成关于李白的代表作"
→ 只修改第2页的topic和key_points，第1页、第3页等完全不变

示例3 - 删除某一页：
用户说"删除第3页"
→ 输出时去掉第3页，其他页面保持原顺序

示例4 - 调整顺序：
用户说"把第1页和第2页换个顺序"
→ 第1页和第2页互换位置，内容不变

=== 输出格式要求 ===
- 直接输出JSON数组，以 [ 开头，以 ] 结尾
- 不要加markdown标记，不要加任何解释文字
- key_points 每个页面不超过6条要点
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
# 6. 工具执行函数（真实映射到 Python 函数）— 完全不变
# ==========================================

_agent_state = {
    "current_slides": None,
    "ppt_file_path": None,
    "current_session_id": None  # 新增：存储当前会话 ID，用于数据持久化
}


def _tool_generate_ppt(topic, pages=3):
    """generate_ppt 工具的真实执行函数（仅生成JSON大纲，不生成图片和PPTX文件）"""
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
    except json.JSONDecodeError:
        return f"错误：JSON解析失败。原始输出: {slides_json_str[:200]}"

    _agent_state["current_slides"] = slides_data
    _agent_state["ppt_file_path"] = None

    # 立即持久化 PPT 数据到数据库（每次生成/修改都替换旧数据）
    session_id = _agent_state.get("current_session_id")
    if session_id:
        try:
            save_slides_data(session_id, slides_data)
            print(f"💾 已立即保存 {len(slides_data)} 页 PPT 数据到会话 {session_id[:8]}...")
        except Exception as e:
            print(f"⚠️ 保存 PPT 数据失败: {e}")

    outline_preview = "\n".join(
        [f"  第{i+1}页: {s.get('topic', '未命名')} ({len(s.get('key_points', []))}个要点)" for i, s in enumerate(slides_data)]
    )

    return (f"✅ 已成功生成「{topic}」的课件大纲！共 {len(slides_data)} 页。\n"
            f"\n📋 大纲预览:\n{outline_preview}\n"
            f"\n💡 你可以随时提出修改意见调整内容，确认无误后点击「导出PPT」即可生成最终文件。")


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
            result = list(original)
            result[i], result[j] = result[j], result[i]
            print(f"  🔧 代码级交换: 第{i+1}页 ↔ 第{j+1}页")
            print(f"  ✅ 交换完成")
            return result

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

    original_slides = _agent_state["current_slides"]
    orig_count = len(original_slides)

    current_json_str = json.dumps(original_slides, ensure_ascii=False, indent=2)
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
        new_count = len(updated_data)
        print(f"  📊 意图检测: {intent} | 原始{orig_count}页 → 模型返回{new_count}页")

        final_data = _safe_merge_slides(original_slides, updated_data, intent, feedback)
        _agent_state["current_slides"] = final_data
        _agent_state["ppt_file_path"] = None

        # 立即持久化修改后的 PPT 数据到数据库（替换旧数据）
        session_id = _agent_state.get("current_session_id")
        if session_id:
            try:
                save_slides_data(session_id, final_data)
                print(f"💾 已立即保存修改后的 {len(final_data)} 页 PPT 数据到会话 {session_id[:8]}...")
            except Exception as e:
                print(f"⚠️ 保存修改后的 PPT 数据失败: {e}")

        outline_preview = "\n".join([
            f"  第{i+1}页: {s.get('topic', '未命名')} ({len(s.get('key_points', []))}个要点)"
            for i, s in enumerate(final_data)
        ])

        return (
            f"✅ 已根据你的意见完成修改！\n"
            f"修改内容: {feedback}\n"
            f"课件从 {orig_count} 页更新为 {len(final_data)} 页。\n"
            f"\n📋 更新后的大纲:\n{outline_preview}\n"
            f"\n💡 如需继续调整请告诉我，确认无误后点击「导出PPT」生成最终文件。"
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
    """export_ppt 工具的真实执行函数（最终落地：生成封面图→写PPTX文件→返回下载路径）"""
    print(f"\n[🔧 工具执行] export_ppt → 开始生成最终PPT文件")

    if not _agent_state.get("current_slides"):
        return "错误：当前没有可导出的课件，请先生成课件。"

    slides_data = _agent_state["current_slides"]

    print(f"  🖼️ 正在为 {len(slides_data)} 页幻灯片生成封面图片...")
    for i, slide in enumerate(slides_data):
        slides_data[i] = generate_cover(i + 1, slide)
        print(f"  ✓ 第{i+1}页封面已生成")

    output_file = os.path.join(os.path.dirname(CURRENT_DIR), "ppts", "AI_Auto_Generated_Courseware.pptx")

    print(f"  📦 正在写入PPTX文件: {output_file}")
    export_to_ppt(slides_data, output_file)

    _agent_state["ppt_file_path"] = output_file

    file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
    size_str = f"{file_size / 1024:.1f} KB" if file_size < 1024 * 1024 else f"{file_size / (1024*1024):.1f} MB"

    return (f"🎉 您的PPT课件《{slides_data[0]['topic']}》已经准备好啦！\n\n"
            f"您可以点击以下链接直接下载：\n"
            f"📥 **[下载 PPT 课件 (AI_Auto_Generated_Courseware.pptx)](http://127.0.0.1:8000/downloads/AI_Auto_Generated_Courseware.pptx)**\n\n"
            f"文件大小: {size_str}，共 {len(slides_data)} 页。")


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


AVAILABLE_TOOLS = {
    "generate_ppt": _tool_generate_ppt,
    "modify_ppt": _tool_modify_ppt,
    "export_ppt": _tool_export_ppt,
    "search_textbook": _tool_search_textbook
}


# ==========================================
# 7. Agent 主循环（标准 OpenAI Function Calling 双向闭环）
# ==========================================

AGENT_SYSTEM_PROMPT = (
    "你是一个AI教学助手老师。你可以使用以下工具来帮助学生:\n"
    "- generate_ppt: 根据主题和页数【从零开始生成】全新的PPT课件（仅限PPT/幻灯片格式）\n"
    "- modify_ppt: 【在已有课件基础上】修改内容（增加/删除/调整页面、修改文字）\n"
    "- export_ppt: 导出最终PPT文件\n"
    "- search_textbook: 从教材知识库检索权威知识点答案\n\n"
    "=== 关键规则（必须严格遵守） ===\n"
    "1. 【generate_ppt 使用时机】：仅当用户【第一次】要求做PPT，或明确说“重新做/从头开始”时调用。\n"
    "   ⚠️ 以下情况【绝对不要】调用 generate_ppt：\n"
    "   - 用户要求「教案」「教学设计」「教学计划」「讲课稿」「备课笔记」等纯文字内容 → 直接用文字回复！\n"
    "   - 用户明确说了「不是PPT」「不要幻灯片」→ 绝对不调此工具！\n"
    "   - 用户只是想让你讲解、分析、讨论某个知识点 → 用文字回复或调 search_textbook\n"
    "2. 【modify_ppt 使用时机】：只要之前已经生成过课件，用户说的任何调整都调用 modify_ppt！包括但不限于：\n"
    "   - “增加一页xxx” / “加一页关于xxx的内容” → 调用 modify_ppt（不是 generate_ppt！）\n"
    "   - “把第x页改成xxx” / “修改第x页” → 调用 modify_ppt\n"
    "   - “删除第x页” / “去掉xxx那一页” → 调用 modify_ppt\n"
    "   - “调换顺序” / “把xx移到前面” → 调用 modify_ppt\n"
    "   - 任何包含“改/修/加/删/换/调整”关键词的请求 → 全部调用 modify_ppt\n"
    "3. 当学生确认无误要求下载/导出时，调用 export_ppt\n"
    "4. 当学生询问具体的学术知识点时，优先调用 search_textbook\n"
    "5. 【纯文字需求直接回复】教案、讲解、分析、闲聊等不需要任何工具的需求，直接用你的知识回答即可\n\n"
    "⚠️ 特别提醒：如果用户已有课件但说了类似“帮我做个杜甫的生平”，这应该是在现有基础上【增加】，必须调用 modify_ppt，绝对不能丢掉原有内容重新生成！\n\n"
    "重要：当工具执行完成后，你需要用自然语言向学生汇报结果。"
)


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
