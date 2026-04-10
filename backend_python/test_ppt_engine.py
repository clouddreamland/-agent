"""
独立测试脚本 - 诊断 PPT Engine V2 是否正常工作

使用方法:
    cd backend_python
    python test_ppt_engine.py
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_import():
    """测试 1: 导入是否正常"""
    print("=" * 60)
    print("测试 1: 检查模块导入")
    print("=" * 60)
    
    tests = [
        ("pptx (python-pptx)", "from pptx import Presentation"),
        ("svg_to_pptx 包", "from svg_to_pptx import create_pptx_with_native_svg"),
        ("pptx_builder", "from svg_to_pptx.pptx_builder import create_pptx_with_native_svg"),
        ("drawingml_converter", "from svg_to_pptx.drawingml_converter import convert_svg_to_slide_shapes"),
        ("SlideDesigner", "from ppt_engine_v2 import SlideDesigner"),
        ("export_to_ppt", "from ppt_engine_v2 import export_to_ppt"),
    ]
    
    results = []
    for name, stmt in tests:
        try:
            exec(stmt)
            print(f"  ✅ {name}")
            results.append(True)
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            results.append(False)
    
    return all(results)


def test_svg_generation():
    """测试 2: SVG 生成是否正常"""
    print("\n" + "=" * 60)
    print("测试 2: 检查 SVG 生成")
    print("=" * 60)
    
    try:
        from ppt_engine_v2 import SlideDesigner
        
        designer = SlideDesigner(color_scheme="professional_blue")
        
        test_slide = {
            "topic": "测试标题",
            "key_points": ["要点1：这是第一行文字", "要点2：这是第二行文字"],
            "filename": None
        }
        
        svg_content = designer.generate_slide_svg(test_slide, slide_num=1)
        
        if svg_content and len(svg_content) > 100:
            print(f"  ✅ SVG 生成成功 (长度: {len(svg_content)} 字符)")
            
            checks = [
                ("<svg" in svg_content, "包含 <svg> 标签"),
                ("linearGradient" in svg_content or "bg_grad" in svg_content, "包含渐变背景"),
                ("Microsoft YaHei" in svg_content, "指定了字体"),
                ("</svg>" in svg_content, "SVG 结构完整"),
            ]
            
            for check, desc in checks:
                if check:
                    print(f"    ✅ {desc}")
                else:
                    print(f"    ⚠️  {desc} - 可能缺失")
            
            return True
        else:
            print(f"  ❌ SVG 内容过短或不完整")
            return False
            
    except Exception as e:
        print(f"  ❌ SVG 生成失败: {e}")
        traceback.print_exc()
        return False


def test_ppt_export():
    """测试 3: 完整的 PPT 导出流程"""
    print("\n" + "=" * 60)
    print("测试 3: 检查完整 PPT 导出流程")
    print("=" * 60)
    
    try:
        from ppt_engine_v2 import export_to_ppt
        
        test_data = [
            {
                "topic": "光合作用的概念",
                "key_points": [
                    "绿色植物利用光能将 CO₂ 和 H₂O 转化为有机物",
                    "释放氧气，储存能量"
                ],
                "filename": None
            },
            {
                "topic": "光反应阶段",
                "key_points": [
                    "发生在叶绿体类囊体薄膜",
                    "水光解产生 O₂、[H] 和 ATP"
                ],
                "filename": None
            }
        ]
        
        output_path = "test_output_diagnostic.pptx"
        
        print(f"  📝 测试数据: {len(test_data)} 页幻灯片")
        print(f"  🎨 使用引擎: ppt_engine_v2 (SVG → DrawingML)")
        print(f"  📁 输出路径: {output_path}")
        print()
        
        result = export_to_ppt(test_data, output_path, use_new_engine=True)
        
        if result and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"  ✅ PPT 导出成功!")
            print(f"     文件大小: {file_size / 1024:.1f} KB")
            print(f"     文件路径: {os.path.abspath(output_path)}")
            return True
        else:
            print(f"  ❌ PPT 导出失败 (未生成文件)")
            return False
            
    except Exception as e:
        print(f"  ❌ PPT 导出过程出错: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("\n" + "🔍" * 30)
    print("  PPT Engine V2 诊断工具")
    print("  用于排查集成后的运行时错误")
    print("🔍" * 30 + "\n")
    
    results = []
    
    r1 = test_import()
    results.append(("模块导入", r1))
    
    r2 = test_svg_generation()
    results.append(("SVG 生成", r2))
    
    r3 = test_ppt_export()
    results.append(("PPT 导出", r3))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    all_pass = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status}  {name}")
        if not passed:
            all_pass = False
    
    print()
    if all_pass:
        print("🎉 所有测试通过! PPT Engine V2 工作正常!")
        print("\n下一步:")
        print("  1. 重启后端服务: python api_server.py")
        print("  2. 在前端生成一个测试 PPT")
        print("  3. 如果还有问题，请查看后端控制台的详细错误信息")
    else:
        print("⚠️  部分测试失败，请根据上面的错误信息进行修复")
        print("\n常见解决方案:")
        print("  - ImportError: 安装缺少的包 (pip install <package>)")
        print("  - SVG 生成失败: 检查 SlideDesigner 类的代码")
        print("  - PPT 导出失败: 检查 svg_to_pptx 引擎的兼容性")
    
    return all_pass


if __name__ == "__main__":
    main()
