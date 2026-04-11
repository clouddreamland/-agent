"""Quick smoke test for ppt_master_bridge"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from ppt_master_bridge import (
    generate_fallback_svg,
    extract_svg_from_response,
    generate_all_svg_previews,
    export_via_ppt_master,
    SVG_SYSTEM_PROMPT,
    SCRIPTS_DIR,
    ICONS_DIR
)

print("=" * 60)
print("  PPT Master Bridge - Smoke Test")
print("=" * 60)

# 1. Test fallback SVG generation
cover = generate_fallback_svg("李白的诗歌世界", ["唐代最伟大的浪漫主义诗人"], 1, 3, True)
assert cover.startswith("<svg"), "Cover SVG should start with <svg"
assert cover.endswith("</svg>"), "Cover SVG should end with </svg>"
assert "1280" in cover, "Should have 1280 width"
assert "720" in cover, "Should have 720 height"
print(f"✅ 封面 SVG: {len(cover)} chars")

content = generate_fallback_svg("诗歌艺术成就", ["豪放飘逸", "想象力丰富", "乐府革新"], 2, 3)
assert content.startswith("<svg"), "Content SVG should start with <svg"
assert "诗歌艺术成就" in content, "Should contain topic"
print(f"✅ 内容 SVG: {len(content)} chars")

# 2. Test SVG extraction
test_cases = [
    ("<svg viewBox='0 0 1280 720'><rect/></svg>", True),
    ("```xml\n<svg viewBox='0 0 1280 720'><rect/></svg>\n```", True),
    ("<think>blah</think><svg viewBox='0 0 1280 720'><rect/></svg>", True),
    ("no svg here", False),
]
for text, should_find in test_cases:
    result = extract_svg_from_response(text)
    if should_find:
        assert result is not None, f"Should extract SVG from: {text[:40]}..."
    else:
        assert result is None, f"Should NOT extract SVG from: {text[:40]}..."
print(f"✅ SVG extraction: {len(test_cases)} test cases passed")

# 3. Check ppt-master paths
print(f"✅ Scripts dir exists: {SCRIPTS_DIR.exists()}")
print(f"✅ Icons dir exists: {ICONS_DIR.exists()}")

# 4. Test System Prompt
assert len(SVG_SYSTEM_PROMPT) > 1000, "System prompt should be substantial"
assert "1280" in SVG_SYSTEM_PROMPT
assert "720" in SVG_SYSTEM_PROMPT
assert "KaiTi" in SVG_SYSTEM_PROMPT
assert "#8B1A1A" in SVG_SYSTEM_PROMPT
print(f"✅ System prompt: {len(SVG_SYSTEM_PROMPT)} chars, contains all key elements")

print()
print("🎉 All smoke tests passed!")
print()
