import os
import requests
from http import HTTPStatus

# 如果使用阿里通义万相，请确保安装了依赖库 (pip install dashscope)
import dashscope

# ==========================================
# 1. API 密钥配置区
# ==========================================
# 请将这里的 Key 替换为你申请的真实 API Key
dashscope.api_key = "sk-5fdd25047c7e48e3a771c43ee5156f79"

# ==========================================
# 2. 画图提示词模板
# ==========================================
TONGYI_PROMPT = '''
请为以下教学 PPT 页面创作一张高质量的配图。
本页主题：{topic}
参考要点（仅作为画面意境参考，绝不要在图片中写出这些文字）：
{key_points}
要求：画面风格专业、唯美、具有艺术感，适合作为高中文学课件的插图。绝对不要在图片中生成任何文字或字母！
'''


def generate_cover(page, module):
    """
    根据传入的 PPT 单页数据（包含 topic 和 key_points），调用 AI 画图接口，
    并将生成的图片下载到本地 images 文件夹，最后将本地路径写入数据字典中返回。
    """
    print(f"🎨 正在为第 {page} 页PPT生成配图，主题: {module.get('topic', '无标题')} ...")

    # 拼接要点用于画图提示词
    key_points_str = "\n".join(module.get("key_points", []))
    prompt = TONGYI_PROMPT.format(topic=module.get("topic", ""), key_points=key_points_str)

    # 确保存放图片的本地目录存在
    save_dir = "images"
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    image_filename = os.path.join(save_dir, f"image_{page}.jpg")

    # ==========================================
    # 3. 核心 API 调用接口预留区
    # 这里的逻辑是完全解耦的，你可以随时替换成别的 API
    # ==========================================
    try:
        # --------------------------------------------------
        # [方案 A：调用真实 API 示例 (通义万相)]
        # --------------------------------------------------
        rsp = dashscope.ImageSynthesis.call(
            model=dashscope.ImageSynthesis.Models.wanx_v1,
            prompt=prompt,
            n=1,
            size='1024*1024'  # 推荐 1:1 或 16:9 比例
        )

        if rsp.status_code == HTTPStatus.OK:
            image_url = rsp.output.results[0].url

            # 下载图片到本地
            response = requests.get(image_url)
            if response.status_code == 200:
                with open(image_filename, "wb") as f:
                    f.write(response.content)
                print(f"✅ 第 {page} 页配图已保存至: {image_filename}")
                module["filename"] = image_filename
            else:
                print(f"❌ 图片下载失败，HTTP 状态码: {response.status_code}")
                module["filename"] = None
        else:
            print(f"❌ 调用画图 API 失败, 错误码: {rsp.code}, 错误信息: {rsp.message}")
            module["filename"] = None

        # --------------------------------------------------
        # [方案 B：断网/无 Key 测试占位 (Mock)]
        # 如果你暂时不想调用真实的 API 浪费额度，或者没有网络，
        # 可以把上面的方案 A 注释掉，打开下面这两行代码。
        # 这样它会假装生成失败，排版引擎拿到 None 后，会自动只排版文字。
        # --------------------------------------------------
        # print(f"⚠️ 触发占位接口：跳过生成，假设第 {page} 页不需要图片。")
        # module["filename"] = None

    except Exception as e:
        print(f"❌ 画图接口发生异常: {e}")
        module["filename"] = None

    return module


# ==========================================
# 4. 模块独立测试代码
# ==========================================
if __name__ == "__main__":
    test_slide = {
        "topic": "《将进酒》的情感张力",
        "key_points": [
            "开篇悲凉：黄河之水天上来",
            "转折狂放：人生得意须尽欢"
        ]
    }

    print("\n--- 开始独立测试 image_api.py ---")
    result = generate_cover(1, test_slide)
    print("\n处理后的字典数据（准备传给排版引擎）：\n", result)