"""PPT Master Bridge - 将 ppt-master 专业级 SVG 生成能力接入 AI 教学智能体

核心职责:
1. 通过 LLM 直接生成高质量古典中国风 SVG 幻灯片（替代旧的硬编码 SlideDesigner）
2. 调用 ppt-master 的后处理管线（finalize_svg → svg_to_pptx）导出 PPTX
"""

import os
import sys
import re
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

# ==========================================
# 路径配置
# ==========================================
CURRENT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = CURRENT_DIR.parent
PPT_MASTER_ROOT = PROJECT_ROOT / "ppt-master-main"
SKILLS_DIR = PPT_MASTER_ROOT / "skills" / "ppt-master"
SCRIPTS_DIR = SKILLS_DIR / "scripts"
ICONS_DIR = SKILLS_DIR / "templates" / "icons"
PPTS_DIR = PROJECT_ROOT / "ppts"

# 确保输出目录存在
PPTS_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================
# 古典中国风 SVG 生成 System Prompt
# ==========================================
SVG_SYSTEM_PROMPT = """你是一位世界级的 SVG 演示文稿视觉设计大师，精通古典中国风高端设计。你的任务是为幻灯片生成一个精美绝伦的完整 SVG 文件。

## 画布规格
viewBox="0 0 1280 720"  width="1280"  height="720"

## 古典中国风配色体系

| 角色 | HEX | 说明 |
|------|-----|------|
| 背景 | #F5F0E8 | 宣纸米色 |
| 卡片/次背景 | #EDE4D3 | 淡绢色 |
| 朱砂红(主色) | #8B1A1A | 印章、标题强调 |
| 松柏绿(辅色) | #2F4F4F | 自然、沉稳 |
| 古铜金(点缀) | #B8860B | 装饰线、高贵感 |
| 墨色(标题) | #1C1C1C | 浓墨重彩 |
| 正文色 | #3C2415 | 深褐墨 |
| 次要文字 | #8B7D6B | 旧纸灰 |
| 边框/分割 | #C4B89C | 绢帛色 |

## 字体体系
- 标题: KaiTi, SimSun, serif
- 正文: SimSun, Microsoft YaHei, serif
- 强调: SimHei, sans-serif
- 英文/数字: Georgia, Arial, serif

## 字号体系(px)
| 用途 | 大小 | 字重 |
|------|------|------|
| 封面大标题 | 56-72px | bold |
| 页面标题 | 28-36px | bold |
| 副标题 | 18-24px | normal |
| 正文内容 | 18-22px | normal |
| 注释/页脚 | 12-14px | normal |

## 古典设计元素指南

### 封面页设计
- 大面积留白，呼吸感充足
- 标题区域：大号楷体标题 + 下方古铜金细装饰线
- 水墨装饰：用 radialGradient 模拟水墨晕染效果（从#1C1C1C到透明，fill-opacity控制浓淡）
- 印章元素：朱砂红圆角方形(rx=4) + 白色竖排小字
- 底部信息栏：日期、机构名，用淡色分隔线与正文区隔

### 内容页设计
- 顶部品牌条：6px 高的朱砂红横线 (rect x=0 y=0 w=1280 h=6 fill=#8B1A1A)
- 页面标题：楷体 28-32px 墨色 (x=60 y=55)
- 标题下装饰线：古铜金细线 (rect x=60 y=70 w=120 h=3 fill=#B8860B)
- 卡片：淡绢色背景 + 细边框(stroke=#C4B89C) + filter阴影
- 要点前缀：圆形装饰点(circle r=5 fill=#8B1A1A) 或 emoji
- 页脚：居中页码 (y=700, font-size=12, fill=#8B7D6B)

### 装饰元素(SVG实现方式)
- 祥云：path 绘制卷曲云纹 fill=#1C1C1C fill-opacity=0.05
- 回纹边框：多个小rect组合 stroke=#C4B89C stroke-width=1
- 水墨渐变：radialGradient + circle/ellipse 从墨色到透明
- 金色分隔：rect h=2 fill=#B8860B
- 竹节分隔：两条平行细线 + 中间圆点

## SVG 绝对禁止特性（违反则无法导出PPTX）
clipPath | mask | <style>标签 | class属性 | foreignObject | <symbol>+<use> | textPath | @font-face | <animate> | <script> | marker/marker-end | rgba()/hsla()

## SVG 必须遵守的规则
1. 颜色只用HEX值(如#8B1A1A)，透明度用 fill-opacity / stroke-opacity（禁止rgba）
2. 禁止 <g opacity="...">（组透明度），改为在每个子元素上单独设 fill-opacity
3. 背景用 <rect width="1280" height="720" fill="#F5F0E8"/>
4. 文本换行用多个 <text> 元素或 <tspan>（禁止foreignObject）
5. 箭头用 <polygon> 三角形（禁止marker）
6. 图标统一用 emoji: <text font-size="28">🎯</text>
7. 相关元素用 <g> 分组（卡片、页头、页脚各自一组）

## 阴影效果（推荐在卡片上使用）
<defs>
  <filter id="shadow" x="-15%" y="-15%" width="140%" height="140%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="10"/>
    <feOffset dx="0" dy="5" result="ob"/>
    <feFlood flood-color="#000000" flood-opacity="0.12" result="sc"/>
    <feComposite in="sc" in2="ob" operator="in" result="s"/>
    <feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>

## 渐变使用方式（推荐用于背景装饰）
<defs>
  <radialGradient id="inkWash" cx="80%" cy="20%" r="50%">
    <stop offset="0%" stop-color="#1C1C1C" stop-opacity="0.08"/>
    <stop offset="100%" stop-color="#1C1C1C" stop-opacity="0"/>
  </radialGradient>
</defs>

## 输出要求
- **只输出纯 SVG 代码**
- 以 <svg xmlns="http://www.w3.org/2000/svg" 开头
- 以 </svg> 结尾
- 不要加 markdown 代码块标记
- 不要加任何解释性文字
- 不要加 XML 声明"""


# ==========================================
# 现代文学 SVG 生成 System Prompt
# ==========================================
SVG_PROMPT_MODERN_LITERARY = """你是一位世界级的 SVG 演示文稿视觉设计大师，精通现代文学极简风格。你的任务是为幻灯片生成一个精美绝伦的完整 SVG 文件。

## 画布规格
viewBox="0 0 1280 720"  width="1280"  height="720"

## 现代文学配色体系

| 角色 | HEX | 说明 |
|------|-----|------|
| 背景 | #F8F9FA | 极简灰白 |
| 卡片/次背景 | #FFFFFF | 纯白卡片 |
| 深海蓝(主色) | #1E3A5F | 标题、强调、品牌条 |
| 浅薰衣草(辅色) | #D1C4E9 | 装饰、淡色块 |
| 浆果红(点缀) | #E91E63 | 高亮强调、装饰线 |
| 标题色 | #263238 | 深灰黑 |
| 正文色 | #37474F | 中灰黑 |
| 次要文字 | #90A4AE | 银灰 |
| 边框/分割 | #ECEFF1 | 浅灰 |

## 字体体系
- 标题: Microsoft YaHei, PingFang SC, sans-serif
- 正文: PingFang SC, Microsoft YaHei, sans-serif
- 强调: SimHei, sans-serif
- 英文/数字: Georgia, Arial, serif

## 字号体系(px)
| 用途 | 大小 | 字重 |
|------|------|------|
| 封面大标题 | 56-72px | bold |
| 页面标题 | 28-36px | bold |
| 副标题 | 18-24px | normal |
| 正文内容 | 18-22px | normal |
| 注释/页脚 | 12-14px | normal |

## 现代文学设计元素指南

### 封面页设计
- 极大留白，干净纯粹
- 标题区域：大号标题 + 下方浆果红细装饰线 (rect h=3 fill=#E91E63)
- 几何装饰：角落放置淡薰衣草色圆形 (circle fill=#D1C4E9 fill-opacity=0.15)
- 底部信息栏：淡灰分隔线与页码

### 内容页设计
- 顶部品牌条：6px 高的深海蓝横线 (rect x=0 y=0 w=1280 h=6 fill=#1E3A5F)
- 页面标题：28-32px 深灰黑 (x=60 y=55)
- 标题下装饰线：浆果红细线 (rect x=60 y=70 w=120 h=3 fill=#E91E63)
- 卡片：纯白背景 + 浅灰边框(stroke=#ECEFF1) + filter阴影
- 要点前缀：圆形装饰点(circle r=5 fill=#1E3A5F) 或 emoji
- 页脚：居中页码 (y=700, font-size=12, fill=#90A4AE)

### 装饰元素(SVG实现方式)
- 几何色块：rect/circle 用 fill-opacity=0.08~0.15 的淡色
- 极简细线：rect h=1 fill=#ECEFF1
- 留白呼吸感：内容区域大量留白
- 浅色渐变：linearGradient 从背景色到浅薰衣草

## SVG 绝对禁止特性（违反则无法导出PPTX）
clipPath | mask | <style>标签 | class属性 | foreignObject | <symbol>+<use> | textPath | @font-face | <animate> | <script> | marker/marker-end | rgba()/hsla()

## SVG 必须遵守的规则
1. 颜色只用HEX值，透明度用 fill-opacity / stroke-opacity（禁止rgba）
2. 禁止 <g opacity="..."> ，改为在每个子元素上单独设 fill-opacity
3. 背景用 <rect width="1280" height="720" fill="#F8F9FA"/>
4. 文本换行用多个 <text> 元素或 <tspan>（禁止foreignObject）
5. 箭头用 <polygon> 三角形（禁止marker）
6. 图标统一用 emoji
7. 相关元素用 <g> 分组

## 阴影效果
<defs>
  <filter id="shadow" x="-15%" y="-15%" width="140%" height="140%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="10"/>
    <feOffset dx="0" dy="5" result="ob"/>
    <feFlood flood-color="#000000" flood-opacity="0.08" result="sc"/>
    <feComposite in="sc" in2="ob" operator="in" result="s"/>
    <feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>

## 输出要求
- **只输出纯 SVG 代码**
- 以 <svg xmlns="http://www.w3.org/2000/svg" 开头
- 以 </svg> 结尾
- 不要加 markdown 代码块标记
- 不要加任何解释性文字
- 不要加 XML 声明"""


# ==========================================
# 复古手稿 SVG 生成 System Prompt
# ==========================================
SVG_PROMPT_VINTAGE_JOURNAL = """你是一位世界级的 SVG 演示文稿视觉设计大师，精通复古手稿风格设计。你的任务是为幻灯片生成一个精美绝伦的完整 SVG 文件。

## 画布规格
viewBox="0 0 1280 720"  width="1280"  height="720"

## 复古手稿配色体系

| 角色 | HEX | 说明 |
|------|-----|------|
| 背景 | #E3D9C6 | 仿古牛皮纸 |
| 卡片/次背景 | #D7CCC8 | 淡赭石 |
| 咖啡墨(主色) | #4E342E | 核心强调 |
| 褐石色(辅色) | #8D6E63 | 柔和辅助 |
| 锈红(点缀) | #BF360C | 装饰线、高光 |
| 标题色 | #2D1A10 | 深褐墨 |
| 正文色 | #3E2723 | 深棕 |
| 次要文字 | #8D6E63 | 褐石灰 |
| 边框/分割 | #BCAAA4 | 淡木色 |

## 字体体系
- 标题: KaiTi, SimSun, serif
- 正文: SimSun, serif
- 强调: SimHei, sans-serif
- 英文/数字: Georgia, serif

## 字号体系(px)
| 用途 | 大小 | 字重 |
|------|------|------|
| 封面大标题 | 56-72px | bold |
| 页面标题 | 28-36px | bold |
| 副标题 | 18-24px | normal |
| 正文内容 | 18-22px | normal |
| 注释/页脚 | 12-14px | normal |

## 复古手稿设计元素指南

### 封面页设计
- 牛皮纸底色，厚重怎旧感
- 标题区域：大号楷体标题 + 下方锈红细装饰线 (rect h=3 fill=#BF360C)
- 复古边框：双线矩形边框 (rect stroke=#BCAAA4 stroke-width=2，外套一个稍大的 rect stroke=#8D6E63)
- 印花装饰：角落圆纹图案 (circle fill-opacity=0.06)
- 底部信息栏：淡褐分隔线与页码

### 内容页设计
- 顶部品牌条：6px 高的咖啡墨横线 (rect x=0 y=0 w=1280 h=6 fill=#4E342E)
- 页面标题：楷体 28-32px 深褐墨 (x=60 y=55)
- 标题下装饰线：锈红细线 (rect x=60 y=70 w=120 h=3 fill=#BF360C)
- 卡片：淡赫石背景 + 褐灰边框(stroke=#BCAAA4) + filter阴影
- 要点前缀：圆形装饰点(circle r=5 fill=#4E342E)
- 页脚：居中页码 (y=700, font-size=12, fill=#8D6E63)

### 装饰元素(SVG实现方式)
- 复古边框：双线 rect 组合 stroke=#BCAAA4 stroke-width=1~2
- 印花圆纹：circle/ellipse fill=#4E342E fill-opacity=0.04
- 粗糙纹理：多个细小 rect 随机分布 fill-opacity=0.02
- 锈红分隔：rect h=2 fill=#BF360C

## SVG 绝对禁止特性（违反则无法导出PPTX）
clipPath | mask | <style>标签 | class属性 | foreignObject | <symbol>+<use> | textPath | @font-face | <animate> | <script> | marker/marker-end | rgba()/hsla()

## SVG 必须遵守的规则
1. 颜色只用HEX值，透明度用 fill-opacity / stroke-opacity（禁止rgba）
2. 禁止 <g opacity="..."> ，改为在每个子元素上单独设 fill-opacity
3. 背景用 <rect width="1280" height="720" fill="#E3D9C6"/>
4. 文本换行用多个 <text> 元素或 <tspan>（禁止foreignObject）
5. 箭头用 <polygon> 三角形（禁止marker）
6. 图标统一用 emoji
7. 相关元素用 <g> 分组

## 阴影效果
<defs>
  <filter id="shadow" x="-15%" y="-15%" width="140%" height="140%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="10"/>
    <feOffset dx="0" dy="5" result="ob"/>
    <feFlood flood-color="#000000" flood-opacity="0.10" result="sc"/>
    <feComposite in="sc" in2="ob" operator="in" result="s"/>
    <feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>

## 输出要求
- **只输出纯 SVG 代码**
- 以 <svg xmlns="http://www.w3.org/2000/svg" 开头
- 以 </svg> 结尾
- 不要加 markdown 代码块标记
- 不要加任何解释性文字
- 不要加 XML 声明"""


# ==========================================
# 竹林书院 SVG 生成 System Prompt
# ==========================================
SVG_PROMPT_BAMBOO_STUDY = """你是一位世界级的 SVG 演示文稿视觉设计大师，精通竹林书院清幽自然风格。你的任务是为幻灯片生成一个精美绝伦的完整 SVG 文件。

## 画布规格
viewBox="0 0 1280 720"  width="1280"  height="720"

## 竹林书院配色体系

| 角色 | HEX | 说明 |
|------|-----|------|
| 背景 | #F1F8E9 | 淡青竹 |
| 卡片/次背景 | #DCEDC8 | 嫩芽绿 |
| 苍翠绿(主色) | #33691E | 核心强调 |
| 草莉绿(辅色) | #689F38 | 柔和辅助 |
| 木质褐(点缀) | #795548 | 装饰线、木纹感 |
| 标题色 | #1B5E20 | 深林绿 |
| 正文色 | #2E7D32 | 森林绿 |
| 次要文字 | #81C784 | 淡树绿 |
| 边框/分割 | #C5E1A5 | 嫩叶色 |

## 字体体系
- 标题: KaiTi, SimSun, serif
- 正文: SimSun, Microsoft YaHei, sans-serif
- 强调: SimHei, sans-serif
- 英文/数字: Georgia, Arial, serif

## 字号体系(px)
| 用途 | 大小 | 字重 |
|------|------|------|
| 封面大标题 | 56-72px | bold |
| 页面标题 | 28-36px | bold |
| 副标题 | 18-24px | normal |
| 正文内容 | 18-22px | normal |
| 注释/页脚 | 12-14px | normal |

## 竹林书院设计元素指南

### 封面页设计
- 清幽自然感，大面积留白
- 标题区域：大号楷体标题 + 下方木质褐细装饰线 (rect h=3 fill=#795548)
- 竹节装饰：竖向细维矩形模拟竹干 (rect w=3~5 fill=#33691E fill-opacity=0.1)
- 自然晕染：radialGradient 从 #33691E 到透明 (fill-opacity=0.04)
- 底部信息栏：淡叶分隔线与页码

### 内容页设计
- 顶部品牌条：6px 高的苍翠绿横线 (rect x=0 y=0 w=1280 h=6 fill=#33691E)
- 页面标题：楷体 28-32px 深林绿 (x=60 y=55)
- 标题下装饰线：木质褐细线 (rect x=60 y=70 w=120 h=3 fill=#795548)
- 卡片：嫩芽绿背景 + 淡叶边框(stroke=#C5E1A5) + filter阴影
- 要点前缀：圆形装饰点(circle r=5 fill=#33691E)
- 页脚：居中页码 (y=700, font-size=12, fill=#81C784)

### 装饰元素(SVG实现方式)
- 竹节装饰：多条平行细矩 (rect w=3 fill=#33691E fill-opacity=0.06)
- 木纹质感：平行细线组 stroke=#795548 stroke-opacity=0.05
- 自然晕染：radialGradient+ellipse fill-opacity<0.05
- 叶片分隔：圆形+梅花点装饰

## SVG 绝对禁止特性（违反则无法导出PPTX）
clipPath | mask | <style>标签 | class属性 | foreignObject | <symbol>+<use> | textPath | @font-face | <animate> | <script> | marker/marker-end | rgba()/hsla()

## SVG 必须遵守的规则
1. 颜色只用HEX值，透明度用 fill-opacity / stroke-opacity（禁止rgba）
2. 禁止 <g opacity="..."> ，改为在每个子元素上单独设 fill-opacity
3. 背景用 <rect width="1280" height="720" fill="#F1F8E9"/>
4. 文本换行用多个 <text> 元素或 <tspan>（禁止foreignObject）
5. 箭头用 <polygon> 三角形（禁止marker）
6. 图标统一用 emoji
7. 相关元素用 <g> 分组

## 阴影效果
<defs>
  <filter id="shadow" x="-15%" y="-15%" width="140%" height="140%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="10"/>
    <feOffset dx="0" dy="5" result="ob"/>
    <feFlood flood-color="#000000" flood-opacity="0.10" result="sc"/>
    <feComposite in="sc" in2="ob" operator="in" result="s"/>
    <feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>

## 输出要求
- **只输出纯 SVG 代码**
- 以 <svg xmlns="http://www.w3.org/2000/svg" 开头
- 以 </svg> 结尾
- 不要加 markdown 代码块标记
- 不要加任何解释性文字
- 不要加 XML 声明"""


# ==========================================
# 风格映射字典：color_scheme -> System Prompt
# ==========================================
STYLE_PROMPT_MAP = {
    "classic_shanshui": SVG_SYSTEM_PROMPT,
    "modern_literary": SVG_PROMPT_MODERN_LITERARY,
    "vintage_journal": SVG_PROMPT_VINTAGE_JOURNAL,
    "bamboo_study": SVG_PROMPT_BAMBOO_STUDY,
}

STYLE_DISPLAY_NAMES = {
    "classic_shanshui": "古典水墨（宣纸底 · 朱砂红 · 楷体）",
    "modern_literary": "现代文学（极简白 · 深海蓝 · 雅黑）",
    "vintage_journal": "复古手稿（牛皮纸 · 咖啡墨 · 楷体）",
    "bamboo_study": "竹林书院（淡青竹 · 苍翠绿 · 楷体）",
}


# ==========================================
# SVG 提取与备用方案
# ==========================================

def _escape_xml(text):
    """转义 XML 特殊字符"""
    if not text:
        return ""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def extract_svg_from_response(text):
    """从 LLM 响应中提取 SVG 代码（兼容 markdown 包裹、thinking 标签等）"""
    if not text:
        return None

    # 1. 去掉可能的 <think>...</think> 标签（DeepSeek-reasoner）
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)

    # 2. 去掉 markdown 代码块
    text = re.sub(r'```(?:xml|svg|html)?\s*\n?', '', text)
    text = re.sub(r'```\s*', '', text)

    # 3. 匹配 <svg...>...</svg>
    match = re.search(r'(<svg\b[^>]*>.*?</svg>)', text.strip(), re.DOTALL)
    if match:
        return match.group(1)

    # 4. 整段文本可能就是 SVG
    stripped = text.strip()
    if stripped.startswith('<svg') and stripped.endswith('</svg>'):
        return stripped

    return None


def generate_fallback_svg(topic, key_points, slide_num, total_slides, is_cover=False):
    """备用 SVG 生成器（当 LLM 无法正常返回时使用）"""
    t = _escape_xml(topic)

    if is_cover:
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
  <defs>
    <radialGradient id="inkWash" cx="75%" cy="25%" r="50%">
      <stop offset="0%" stop-color="#1C1C1C" stop-opacity="0.06"/>
      <stop offset="100%" stop-color="#1C1C1C" stop-opacity="0"/>
    </radialGradient>
    <filter id="shadow" x="-15%" y="-15%" width="140%" height="140%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="10"/>
      <feOffset dx="0" dy="5" result="ob"/>
      <feFlood flood-color="#000000" flood-opacity="0.12" result="sc"/>
      <feComposite in="sc" in2="ob" operator="in" result="s"/>
      <feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <rect width="1280" height="720" fill="#F5F0E8"/>
  <ellipse cx="1050" cy="180" rx="400" ry="300" fill="url(#inkWash)"/>
  <rect x="80" y="100" width="5" height="220" rx="2" fill="#B8860B"/>
  <text x="110" y="260" font-family="KaiTi, SimSun, serif" font-size="64" font-weight="bold" fill="#1C1C1C">{t}</text>
  <rect x="110" y="285" width="180" height="4" rx="2" fill="#B8860B"/>
  <text x="110" y="340" font-family="SimSun, serif" font-size="20" fill="#8B7D6B">{_escape_xml(key_points[0] if key_points else "AI 教学智能体 · 自动生成")}</text>
  <rect x="1100" y="560" width="90" height="90" rx="6" fill="#8B1A1A" filter="url(#shadow)"/>
  <text x="1145" y="598" font-family="KaiTi, serif" font-size="22" fill="#FFFFFF" text-anchor="middle">教</text>
  <text x="1145" y="628" font-family="KaiTi, serif" font-size="22" fill="#FFFFFF" text-anchor="middle">学</text>
  <line x1="60" y1="670" x2="1220" y2="670" stroke="#C4B89C" stroke-width="1"/>
  <text x="640" y="700" font-family="Georgia, Arial" font-size="12" fill="#8B7D6B" text-anchor="middle">{slide_num} / {total_slides}</text>
</svg>'''

    # 内容页
    points_svg = ""
    for i, point in enumerate(key_points[:5]):
        y = 155 + i * 105
        points_svg += f'''
  <g>
    <rect x="60" y="{y - 20}" width="1160" height="85" rx="8" fill="#EDE4D3" stroke="#C4B89C" stroke-width="1"/>
    <circle cx="95" cy="{y + 12}" r="5" fill="#8B1A1A"/>
    <text x="120" y="{y + 18}" font-family="SimSun, serif" font-size="20" fill="#3C2415">{_escape_xml(point)}</text>
  </g>'''

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
  <rect width="1280" height="720" fill="#F5F0E8"/>
  <rect x="0" y="0" width="1280" height="6" fill="#8B1A1A"/>
  <text x="60" y="55" font-family="KaiTi, SimSun, serif" font-size="32" font-weight="bold" fill="#1C1C1C">{t}</text>
  <rect x="60" y="70" width="120" height="3" rx="1" fill="#B8860B"/>
  <circle cx="1200" cy="40" r="25" fill="#1C1C1C" fill-opacity="0.04"/>
  <circle cx="1200" cy="40" r="15" fill="#1C1C1C" fill-opacity="0.03"/>{points_svg}
  <line x1="60" y1="680" x2="1220" y2="680" stroke="#C4B89C" stroke-width="1"/>
  <text x="640" y="700" font-family="Georgia, Arial" font-size="12" fill="#8B7D6B" text-anchor="middle">{slide_num} / {total_slides}</text>
</svg>'''


# ==========================================
# LLM SVG 生成核心函数
# ==========================================

def generate_slide_svg_via_llm(client, model_name, slide_data, slide_num, total_slides, color_scheme="classic_shanshui"):
    """调用 LLM 为单页幻灯片生成高质量 SVG 代码"""
    topic = slide_data.get("topic", "无标题")
    key_points = slide_data.get("key_points", [])
    layout = slide_data.get("layout", "content")
    is_cover = (slide_num == 1) or (layout == "cover")

    # 构建每页的用户提示词
    points_text = "\n".join([f"  {i + 1}. {p}" for i, p in enumerate(key_points)])

    if is_cover:
        user_prompt = f"""请生成第 {slide_num}/{total_slides} 页的完整 SVG。这是 **封面页**。

主标题: {topic}
副标题: {key_points[0] if key_points else "AI 教学智能体 · 课件自动生成"}

封面设计要求（请严格使用你的专属配色体系中的颜色，不要自行编造颜色）：
- 大气留白风格，使用你的配色体系中定义的【背景色】
- 标题用大号字体(56-72px)，使用你的配色体系中的【标题字体】和【标题色】
- 标题旁用你的配色体系中的【主色】或【点缀色】做竖条/横条装饰
- 适度添加你的配色体系所定义的特色装饰元素
- 底部分隔线 + 页码信息
- 保持高端、专业的视觉品质"""
    else:
        user_prompt = f"""请生成第 {slide_num}/{total_slides} 页的完整 SVG。这是 **内容页**。

页面标题: {topic}
内容要点:
{points_text}

内容页设计要求（请严格使用你的专属配色体系中的颜色，不要自行编造颜色）：
- 使用你的配色体系中定义的【背景色】
- 顶部6px品牌条，使用你的配色体系中的【主色】
- 标题使用你的配色体系中的【标题字体】(28-32px)，位于 x=60 y=55
- 标题下装饰线，使用你的配色体系中的【点缀色】
- 每个要点用精美的卡片布局展示：
  · 卡片：rect rx=10，使用你的配色体系中的【卡片/次背景色】 + 【边框色】+ filter阴影
  · 要点前用你的【主色】做圆点装饰(circle r=5)
  · 文字 20px，使用你的配色体系中的【正文字体】和【正文色】
- 根据要点数量自动选择布局：
  · 2-3个要点: 竖排大卡片（每个卡片宽1160 高约150）
  · 4-6个要点: 双列卡片（每个宽560 高120 排列2列）
- 内容区域保持充足的留白和呼吸感
- 适度添加你的配色体系中定义的特色装饰元素（保持克制）
- 底部居中页码: {slide_num}/{total_slides}"""

    try:
        print(f"  🎨 正在调用 LLM 生成第 {slide_num} 页 SVG...")
        # 根据 color_scheme 选择对应的风格提示词
        style_prompt = STYLE_PROMPT_MAP.get(color_scheme, SVG_SYSTEM_PROMPT)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": style_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=8192,
            temperature=0.7
        )

        raw_content = response.choices[0].message.content or ""
        svg_code = extract_svg_from_response(raw_content)

        if svg_code:
            print(f"  ✅ 第 {slide_num} 页 SVG 生成成功 ({len(svg_code)} 字符)")
            return svg_code
        else:
            print(f"  ⚠️ 第 {slide_num} 页 SVG 提取失败，使用备用模板")
            return generate_fallback_svg(topic, key_points, slide_num, total_slides, is_cover)

    except Exception as e:
        print(f"  ❌ 第 {slide_num} 页 SVG 生成异常: {e}")
        return generate_fallback_svg(topic, key_points, slide_num, total_slides, is_cover)


def generate_all_svg_previews(client, model_name, slides_data):
    """为整副幻灯片生成所有 SVG 预览（替代旧的 _add_svg_previews）

    Args:
        client: OpenAI 兼容客户端
        model_name: 模型名称
        slides_data: dict，包含 "color_scheme" 和 "slides" 数组

    Returns:
        更新了 preview_svg 的 slides_data
    """
    if not isinstance(slides_data, dict):
        return slides_data

    slides = slides_data.get("slides", [])
    color_scheme = slides_data.get("color_scheme", "classic_shanshui")
    total = len(slides)

    style_display = STYLE_DISPLAY_NAMES.get(color_scheme, color_scheme)

    print(f"\n{'=' * 60}")
    print(f"  🖌️  PPT Master Bridge: 开始生成 {total} 页 SVG")
    print(f"  📐 画布: 1280×720 (16:9)")
    print(f"  🎨 风格: {style_display}")
    print(f"{'=' * 60}")

    for i, slide in enumerate(slides):
        svg = generate_slide_svg_via_llm(client, model_name, slide, i + 1, total, color_scheme)
        slide["preview_svg"] = svg

    print(f"\n  ✨ 全部 {total} 页 SVG 生成完毕！\n")
    return slides_data


# ==========================================
# PPTX 导出管线
# ==========================================

def export_via_ppt_master(slides_data, output_path):
    """使用 ppt-master 的完整管线导出 PPTX

    流程: 保存 SVG → finalize_svg（后处理）→ svg_to_pptx（导出）

    Args:
        slides_data: dict，包含 "slides" 数组，每个 slide 有 "preview_svg"
        output_path: PPTX 输出路径

    Returns:
        成功返回 output_path, 失败返回 None
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. 创建临时项目目录
    temp_dir = Path(tempfile.mkdtemp(prefix="ppt_master_export_"))
    svg_output_dir = temp_dir / "svg_output"
    svg_output_dir.mkdir()

    try:
        # 2. 保存所有 SVG 到 svg_output/
        slides = slides_data.get("slides", []) if isinstance(slides_data, dict) else slides_data

        for i, slide in enumerate(slides):
            svg_content = slide.get("preview_svg", "")
            if not svg_content:
                svg_content = generate_fallback_svg(
                    slide.get("topic", "无标题"),
                    slide.get("key_points", []),
                    i + 1, len(slides)
                )

            # 文件名：序号_标题（截取前10个安全字符）
            safe_topic = re.sub(r'[<>:"/\\|?*]', '', slide.get('topic', '页面'))[:10]
            svg_file = svg_output_dir / f"{i + 1:02d}_{safe_topic}.svg"
            with open(svg_file, "w", encoding="utf-8") as f:
                f.write(svg_content)
            print(f"  📄 已保存 {svg_file.name}")

        # 3. 尝试使用 ppt-master 后处理管线
        if SCRIPTS_DIR.exists():
            print(f"\n  🔄 运行 ppt-master 后处理管线...")
            try:
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "finalize_svg.py"),
                     str(temp_dir), "--only", "flatten-text", "fix-rounded"],
                    capture_output=True, text=True, timeout=60,
                    encoding='utf-8', errors='replace',
                    cwd=str(SCRIPTS_DIR.parent)
                )
                if result.returncode == 0:
                    print(f"  ✅ 后处理完成")
                else:
                    print(f"  ⚠️ 后处理告警: {result.stderr[:200] if result.stderr else '(无详情)'}")
                    # 后处理失败时手动复制到 svg_final
                    svg_final_dir = temp_dir / "svg_final"
                    if not svg_final_dir.exists():
                        shutil.copytree(svg_output_dir, svg_final_dir)
            except Exception as e:
                print(f"  ⚠️ 后处理跳过: {e}")
                svg_final_dir = temp_dir / "svg_final"
                if not svg_final_dir.exists():
                    shutil.copytree(svg_output_dir, svg_final_dir)
        else:
            # ppt-master 不可用，直接复制
            svg_final_dir = temp_dir / "svg_final"
            shutil.copytree(svg_output_dir, svg_final_dir)
            print(f"  ℹ️ ppt-master 脚本不可用，跳过后处理")

        # 4. 导出 PPTX
        print(f"\n  📦 正在导出 PPTX...")
        export_success = False

        # 方案A: 使用 ppt-master 的 svg_to_pptx
        if SCRIPTS_DIR.exists():
            try:
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "svg_to_pptx.py"),
                     str(temp_dir), "-s", "final"],
                    capture_output=True, text=True, timeout=120,
                    encoding='utf-8', errors='replace',
                    cwd=str(SCRIPTS_DIR.parent)
                )

                if result.returncode == 0:
                    pptx_files = list(temp_dir.glob("*.pptx"))
                    if pptx_files:
                        # 优先选不带 _svg 后缀的（原生 shapes 版本）
                        native = [f for f in pptx_files if '_svg' not in f.name]
                        chosen = native[0] if native else pptx_files[0]
                        shutil.copy2(chosen, output_path)
                        print(f"  🎉 PPTX 导出成功 (ppt-master 引擎): {output_path}")
                        export_success = True
                    else:
                        print(f"  ⚠️ ppt-master 未生成 PPTX 文件")
                else:
                    print(f"  ⚠️ ppt-master 导出失败: {result.stderr[:300] if result.stderr else '(无详情)'}")
            except Exception as e:
                print(f"  ⚠️ ppt-master 导出异常: {e}")

        # 方案B: 回退到现有的 export_to_ppt（ppt_engine_v2）
        if not export_success:
            print(f"  🔄 尝试使用备用导出引擎...")
            try:
                from ppt_engine_v2 import export_to_ppt
                export_to_ppt(slides_data, str(output_path))
                if output_path.exists():
                    print(f"  ✅ 备用导出成功: {output_path}")
                    export_success = True
                else:
                    print(f"  ❌ 备用导出未生成文件")
            except Exception as e2:
                print(f"  ❌ 备用导出也失败: {e2}")

        return str(output_path) if export_success else None

    finally:
        # 清理临时目录
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
