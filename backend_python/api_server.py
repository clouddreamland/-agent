import os
import json

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
os.environ["HF_HOME"] = os.path.join(PROJECT_ROOT, "models")

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File
import fitz
import docx
import io
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI as SiliconFlowClient

from llm_api import chat_with_agent
from session_db import (
    create_session, list_sessions, get_session,
    delete_session, get_all_messages, get_slides_data
)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, "ppts")

# ==========================================
# 硅基流动语音识别 (SenseVoiceSmall) 客户端
# ==========================================
SILICON_FLOW_KEY = "sk-brcjhomlsadpzhvjniddxmeqeylryxfqfsauqjkddrezmogu"
silicon_client = SiliconFlowClient(
    api_key=SILICON_FLOW_KEY,
    base_url="https://api.siliconflow.cn/v1"
)

app = FastAPI(title="AI 互动式教学智能体后端中枢")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """应用启动时执行健康检查"""
    print("\n" + "🚀" * 30)
    print("  正在进行系统健康检查...")
    print("🚀" * 30 + "\n")
    
    # 检查 PPT 引擎
    try:
        from ppt_engine_v2 import export_to_ppt, SlideDesigner
        print("✅ PPT Engine V2 加载成功")
        
        # 尝试导入 SVG 转换引擎
        try:
            from svg_to_pptx.pptx_builder import create_pptx_with_native_svg
            print("✅ SVG → DrawingML 转换引擎就绪 (新引擎可用)")
        except ImportError as e:
            print(f"⚠️  SVG 引擎不可用: {e}")
            print("   将使用旧版 python-pptx 引擎作为后备")
            
    except Exception as e:
        print(f"❌ PPT 引擎加载失败: {e}")
    
    # 检查数据库
    try:
        from session_db import _get_conn
        conn = _get_conn()
        conn.execute("SELECT count(*) FROM sessions")
        print("✅ 数据库连接正常")
        conn.close()
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
    
    print("\n✅ 系统启动完成!\n")


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class KbInitRequest(BaseModel):
    texts: list[str]
# ==========================================
# 核心聊天接口111222
# ==========================================

@app.post("/chat")
async def chat(req: ChatRequest):
    """核心聊天接口：接收用户消息，经过 Agent 闭环处理后返回回复"""
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    try:
        # 如果前端没传 session_id，自动创建新会话
        session_id = req.session_id
        if not session_id:
            session_id = create_session()

        result = chat_with_agent(req.message.strip(), session_id=session_id)
        return {
            "status": "success",
            "session_id": session_id,
            "reply": result.get("reply", ""),
            "slides_data": result.get("slides_data"),
            "agent_status": result.get("status", "idle"),
            "file_path": result.get("file_path")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 处理异常: {str(e)}")


# ==========================================
# 会话管理接口
# ==========================================

@app.get("/sessions")
async def get_sessions():
    """获取所有会话列表（按更新时间倒序）"""
    try:
        sessions = list_sessions()
        return {"status": "success", "sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")


@app.post("/sessions")
async def create_new_session():
    """创建一个新会话"""
    try:
        session_id = create_session()
        return {"status": "success", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


@app.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    """删除指定会话及其所有消息"""
    try:
        session = get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        delete_session(session_id)
        return {"status": "success", "message": "会话已删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除会话失败: {str(e)}")


@app.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """获取指定会话的所有历史消息（用于前端展示）"""
    try:
        session = get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = get_all_messages(session_id)
        return {"status": "success", "messages": messages}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取消息失败: {str(e)}")


@app.get("/sessions/{session_id}/slides")
async def get_session_slides(session_id: str):
    """获取指定会话的 PPT 预览数据（用于切换会话时恢复预览）"""
    try:
        session = get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        slides_data = get_slides_data(session_id)
        if slides_data:
            return {
                "status": "success",
                "slides_data": slides_data,
                "has_data": True
            }
        else:
            return {
                "status": "success",
                "slides_data": None,
                "has_data": False,
                "message": "该会话暂无 PPT 数据"
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取 PPT 数据失败: {str(e)}")


# ==========================================
# 知识库 & 文件下载 & 健康检查
# ==========================================

@app.post("/upload_reference")
async def upload_reference(file: UploadFile = File(...)):
    """处理上传的多模态参考资料(PDF/Word)，提取文字并存入知识库"""
    from knowledge_base import add_to_kb
    try:
        content = await file.read()
        filename = file.filename.lower()
        extracted_text = ""
        
        if filename.endswith(".pdf"):
            pdf_document = fitz.open(stream=content, filetype="pdf")
            for page in pdf_document:
                extracted_text += page.get_text() + "\n"
        elif filename.endswith(".docx"):
            doc = docx.Document(io.BytesIO(content))
            extracted_text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        else:
            raise HTTPException(status_code=400, detail="不支持的文件格式，请上传 PDF 或 Word (.docx)")
            
        if not extracted_text.strip():
            return {"status": "success", "message": "文件中未提取到文字内容", "kb_count": 0}
            
        # 简单分段，防止单条过大导致 embedding 失败（这里按 1000 字符分块）
        chunk_size = 1000
        chunks = [extracted_text[i:i+chunk_size] for i in range(0, len(extracted_text), chunk_size)]
        
        # 将文档名字拼在段落前，让检索更准确
        chunks = [f"参考文件《{file.filename}》内容片段:\n{c}" for c in chunks]
        
        count = add_to_kb(chunks)
        return {"status": "success", "message": f"成功读取《{file.filename}》，共解析 {len(extracted_text)} 字，已加入背景知识，你现在可以围绕该资料进行交流和生成了。"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件解析失败: {str(e)}")


@app.post("/kb/init")
async def init_knowledge_base(req: KbInitRequest):
    """初始化/追加知识库内容"""
    from knowledge_base import add_to_kb
    try:
        count = add_to_kb(req.texts)
        return {"status": "success", "total_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"知识库初始化失败: {str(e)}")


@app.get("/downloads/{filename}")
async def download_file(filename: str):
    """静态文件下载接口（PPT 等）"""
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


# ==========================================
# 语音识别接口（硅基流动 SenseVoiceSmall）
# ==========================================
@app.post("/api/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """接收前端录音文件，调用硅基流动 SenseVoiceSmall 进行语音转文字"""
    temp_file = f"temp_{audio.filename}"

    # 1. 把前端发来的音频临时存到本地
    with open(temp_file, "wb") as buffer:
        buffer.write(await audio.read())

    try:
        # 2. 调用硅基流动的语音识别 API
        with open(temp_file, "rb") as audio_data:
            result = silicon_client.audio.transcriptions.create(
                model="FunAudioLLM/SenseVoiceSmall",
                file=audio_data,
                response_format="text"
            )

        print(f"  [语音识别] API原始返回: {result}")

        # 3. 解析识别结果（硅基流动可能返回 JSON 字符串而非纯文本）
        recognized_text = result
        if isinstance(result, str):
            # 尝试解析 JSON 格式的返回值，如 '{"text":"你好"}'
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "text" in parsed:
                    recognized_text = parsed["text"]
            except (json.JSONDecodeError, TypeError):
                # 不是 JSON，直接当纯文本用
                recognized_text = result
        elif hasattr(result, 'text'):
            # 如果是对象类型，取 .text 属性
            recognized_text = result.text

        recognized_text = recognized_text.strip() if recognized_text else ""
        print(f"  [语音识别] 最终文本: {recognized_text}")
        return {"status": "success", "text": recognized_text}

    except Exception as e:
        print(f"  [语音识别] API调用失败: {e}")
        return {"status": "error", "text": f"语音识别失败: {str(e)}"}

    finally:
        # 3. 删除临时音频文件
        if os.path.exists(temp_file):
            os.remove(temp_file)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "AI Teaching Agent"}


if __name__ == "__main__":
    print("=" * 60)
    print("  🚀 AI 教学智能体 - FastAPI 后端服务启动")
    print("=" * 60)
    print(f"  📡 API 地址: http://127.0.0.1:8000")
    print(f"  💬 聊天接口: POST /chat")
    print(f"  📂 会话管理: GET/POST /sessions")
    print(f"  📚 知识库接口: POST /kb/init")
    print(f"  🎙️ 语音识别: POST /api/transcribe")
    print(f"  📥 文件下载: GET /downloads/<filename>")
    print(f"  📂 下载目录: {DOWNLOAD_DIR}")
    print("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=8000)
