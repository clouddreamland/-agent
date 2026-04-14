"""
HTML5 互动小游戏 / 动画创意生成引擎
====================================
将 LLM 的代码生成能力转化为可运行的单文件 HTML5 互动式教学内容。

核心流程：
  1. 根据教师提供的知识点主题，构建专业 Prompt
  2. 调用大模型，要求其输出一段完整的、可独立运行的 HTML/CSS/JS 代码
  3. 从模型返回中提取 HTML 代码块，保存为 .html 文件
  4. 返回文件路径，供 FastAPI 的 /downloads 接口提供下载
"""

import os
import re
import uuid

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "ppts")  # 复用已有的下载目录


# ==========================================
# LLM 提示词：驱动大模型生成高质量 HTML5 互动内容
# ==========================================

HTML5_SYSTEM_PROMPT = """你是一位资深的前端教育游戏开发工程师，同时也是一位创意教学设计师。
你的任务是根据用户提供的教学知识点主题，生成一个「单文件 HTML5 互动小游戏或动画演示」。

=== 严格技术要求 ===
1. 输出的内容必须是一个完整的、可独立运行的 HTML 文件。
2. 所有 CSS 必须写在 <style> 标签内（内联样式表），所有 JS 必须写在 <script> 标签内。
3. 禁止引用任何外部 CDN、外部脚本、外部字体或外部图片链接。一切资源必须自包含。
4. 页面必须能在现代浏览器中直接双击打开并正常运行。

=== 设计美学要求 ===
1. 整体视觉风格必须现代、精致、充满教育趣味感。
2. 使用渐变色背景、圆角卡片、柔和阴影等现代 UI 元素。
3. 配色要鲜明但和谐，推荐使用教育类常见的蓝色、绿色、橙色系。
4. 标题区域要醒目，带有 emoji 装饰，体现教学主题。
5. 必须包含丰富的 CSS 动画效果（如淡入、弹跳、滑动、翻转等），让页面充满活力。
6. 按钮、卡片等交互元素要有 hover 和 active 状态的视觉反馈。

=== 互动玩法要求 ===
根据知识点的性质，你可以自行选择以下某一种或组合多种互动形式：
- 🧠 知识问答（选择题/判断题，答对有动画反馈，答错有鼓励提示）
- 🃏 卡片翻转记忆配对（翻开两张相同知识点卡片即为配对成功）
- 🔗 拖拽连线 / 分类归纳（将知识点拖拽到对应的分类区域）
- 🎯 填空闯关（根据提示补全关键知识点）
- 📊 互动动画演示（用 Canvas 或 CSS 动画可视化展示知识过程）

=== 教育内容要求 ===
1. 游戏内容必须紧密围绕用户给出的教学知识点，不能跑题。
2. 题目/素材至少包含 5-8 个与知识点相关的问题或元素。
3. 必须在页面底部或顶部显示游戏的教学目标说明。
4. 游戏结束时要有成绩总结和鼓励性评语。

=== 输出格式 ===
- 将完整的 HTML 代码包裹在 ```html 和 ``` 标记中输出。
- 代码前后不要加任何解释性文字，只输出代码块。
- HTML 文件的 <title> 标签必须包含知识点主题名称。
- 必须设置 <html lang="zh-CN"> 和 <meta charset="UTF-8">。
"""


def build_html5_prompt(topic):
    """构建 HTML5 互动内容生成的 LLM 请求消息"""
    return [
        {"role": "system", "content": HTML5_SYSTEM_PROMPT},
        {"role": "user", "content": f"请为以下教学知识点生成一个精美的 HTML5 互动小游戏：{topic}"}
    ]


def extract_html_and_save(llm_output, topic="互动游戏"):
    """
    从大模型的返回内容中提取 HTML 代码块，并保存为 .html 文件。

    参数:
        llm_output: str, 大模型的原始返回文本
        topic: str, 知识点主题（用于文件名和日志）

    返回:
        tuple: (file_path, filename) 或 (None, error_message)
    """
    if not llm_output:
        return None, "大模型未返回任何内容"

    # 尝试提取 ```html ... ``` 代码块
    pattern = r'```html\s*([\s\S]*?)```'
    match = re.search(pattern, llm_output)

    if match:
        html_content = match.group(1).strip()
    else:
        # 兜底 1：尝试普通 ``` 块，但里面包含 <html> 标记
        generic_blocks = re.findall(r'```\s*([\s\S]*?)```', llm_output)
        html_content = ""
        for block in generic_blocks:
            if '<html' in block.lower() and '</html>' in block.lower():
                html_content = block.strip()
                break
        
        # 兜底 2：暴力搜索 <!DOCTYPE 或 <html 到 </html> 的范围
        if not html_content:
            start_match = re.search(r'(<!DOCTYPE|<html)', llm_output, re.IGNORECASE)
            if start_match:
                # 找最后一个 </html>
                all_ends = [m.end() for m in re.finditer(r'</html>', llm_output, re.IGNORECASE)]
                if all_ends:
                    html_content = llm_output[start_match.start():all_ends[-1]].strip()
        
        if not html_content:
            # 打印模型输出帮助调试
            print(f"  ⚠️ [HTML提取失败] 模型输出长度: {len(llm_output)} 字符")
            print(f"  ⚠️ 模型输出前500字符: {llm_output[:500]}")
            return None, "无法从模型输出中提取 HTML 代码"

    # 基本校验：确保包含最小必要结构。如果被截断，尝试补全
    if '</html>' not in html_content.lower():
        if '<html' in html_content.lower():
            html_content += "\n</body>\n</html>"
            print("  🔧 检测到 HTML 被截断，已自动补全闭合标签")
        else:
            return None, "提取的 HTML 内容不完整（缺少 <html> 标签）"

    # 生成唯一文件名
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    short_id = uuid.uuid4().hex[:8]
    filename = f"Interactive_Game_{short_id}.html"
    file_path = os.path.join(OUTPUT_DIR, filename)

    # 写入文件
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    file_size = os.path.getsize(file_path)
    print(f"[OK] HTML5 互动内容已保存: {file_path} ({file_size / 1024:.1f} KB)")

    return file_path, filename
