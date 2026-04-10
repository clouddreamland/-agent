import re

def _parse_page_numbers(feedback, max_pages):
    indices = set()

    chinese_nums = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

    for cn, num in chinese_nums.items():
        if f'第{cn}页' in feedback or f'第{cn}' in feedback:
            idx = num - 1
            if 0 <= idx < max_pages:
                indices.add(idx)

    arabic_matches = re.findall(r'第(\d+)页', feedback)
    for m in arabic_matches:
        idx = int(m) - 1
        if 0 <= idx < max_pages:
            indices.add(idx)

    standalone = re.findall(r'(?<!\w)(\d+)(?!\w)页', feedback)
    for m in standalone:
        idx = int(m) - 1
        if 0 <= idx < max_pages:
            indices.add(idx)

    if '最后一页' in feedback or '最后' in feedback:
        indices.add(max_pages - 1)
    if '第一页' in feedback:
        indices.add(0)

    return sorted(indices)

print(_parse_page_numbers("把第八页和第十页交换一下位置", 10))
