"""
会话持久化存储模块 — 基于 SQLite
负责管理对话会话和消息的 CRUD 操作
"""

import os
import uuid
import sqlite3
import json
from datetime import datetime

# 数据库文件路径（和 api_server.py 同目录）
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_history.db")


def _get_conn():
    """获取数据库连接（自动创建表）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 让查询结果可以用列名访问
    conn.execute("PRAGMA journal_mode=WAL")  # 并发性能更好
    conn.execute("PRAGMA foreign_keys=ON")
    _init_tables(conn)
    return conn


def _init_tables(conn):
    """初始化数据库表（如果不存在则创建）+ 迁移旧表结构"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id    TEXT PRIMARY KEY,
            title         TEXT DEFAULT '新对话',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            slides_data   TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    TEXT NOT NULL,
            role          TEXT NOT NULL,
            content       TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, created_at);
    """)
    
    # 数据库迁移：确保 slides_data 列存在（处理旧版本数据库）
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if "slides_data" not in columns:
            print("🔄 检测到旧版数据库结构，正在添加 slides_data 列...")
            conn.execute("ALTER TABLE sessions ADD COLUMN slides_data TEXT DEFAULT NULL")
            conn.commit()
            print("✅ slides_data 列已成功添加")
    except Exception as e:
        print(f"⚠️ 数据库迁移失败: {e}")
    
    conn.commit()


# ==========================================
# 会话管理
# ==========================================

def create_session(title="新对话"):
    """创建新会话，返回 session_id"""
    session_id = str(uuid.uuid4())
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO sessions (session_id, title) VALUES (?, ?)",
            (session_id, title)
        )
        conn.commit()
        print(f"📝 创建新会话: {session_id[:8]}... 标题: {title}")
        return session_id
    finally:
        conn.close()


def list_sessions():
    """列出所有会话（按更新时间倒序），返回 list[dict]"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM sessions "
            "ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_session(session_id):
    """获取单个会话信息"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_session_title(session_id, title):
    """更新会话标题"""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (title, session_id)
        )
        conn.commit()
    finally:
        conn.close()


def delete_session(session_id):
    """删除会话及其所有消息"""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        print(f"🗑️ 已删除会话: {session_id[:8]}...")
    finally:
        conn.close()


# ==========================================
# PPT 数据持久化
# ==========================================

def save_slides_data(session_id, slides_data):
    """
    保存 PPT 幻灯片数据到会话记录中
    参数:
        session_id: 会话 ID
        slides_data: list[dict] 或 None，PPT 数据列表
    """
    conn = _get_conn()
    try:
        json_str = json.dumps(slides_data, ensure_ascii=False) if slides_data else None
        conn.execute(
            "UPDATE sessions SET slides_data = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (json_str, session_id)
        )
        conn.commit()
        print(f"💾 已保存 PPT 数据到会话 {session_id[:8]}... ({len(slides_data) if slides_data else 0} 页)")
    finally:
        conn.close()


def get_slides_data(session_id):
    """
    从数据库获取某会话的 PPT 幻灯片数据
    返回:
        list[dict] 或 None
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT slides_data FROM sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        
        if row and row["slides_data"]:
            try:
                return json.loads(row["slides_data"])
            except json.JSONDecodeError:
                print(f"⚠️ 会话 {session_id[:8]}... 的 PPT 数据 JSON 解析失败")
                return None
        return None
    finally:
        conn.close()


# ==========================================
# 消息管理
# ==========================================

def save_message(session_id, role, content):
    """保存一条消息到数据库，并更新会话的 updated_at"""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content)
        )
        conn.execute(
            "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )
        conn.commit()
    finally:
        conn.close()


def get_history(session_id, limit=20):
    """
    获取某会话的历史消息（只取 user 和 assistant 的消息）
    返回 list[dict]，格式为 [{"role": "user", "content": "..."}, ...]
    limit: 最多返回多少条消息（最近的 N 条）
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE session_id = ? AND role IN ('user', 'assistant') "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, limit)
        ).fetchall()
        # 反转顺序（数据库是倒序取的，需要正序返回）
        messages = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
        return messages
    finally:
        conn.close()


def get_all_messages(session_id):
    """
    获取某会话的所有消息（用于前端展示历史记录）
    返回 list[dict]，包含 role, content, created_at
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id = ? AND role IN ('user', 'assistant') "
            "ORDER BY created_at ASC",
            (session_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ==========================================
# 测试
# ==========================================

if __name__ == "__main__":
    print("🧪 测试 session_db 模块...")

    # 创建会话
    sid = create_session("测试对话")
    print(f"  创建会话: {sid}")

    # 保存消息
    save_message(sid, "user", "你好，帮我做一个PPT")
    save_message(sid, "assistant", "好的，请告诉我主题和页数")
    save_message(sid, "user", "关于光合作用，5页")
    save_message(sid, "assistant", "已为你生成光合作用的课件大纲")

    # 获取历史
    history = get_history(sid, limit=20)
    print(f"  历史消息 ({len(history)} 条):")
    for msg in history:
        print(f"    [{msg['role']}] {msg['content'][:50]}")

    # 列出会话
    sessions = list_sessions()
    print(f"  会话列表 ({len(sessions)} 个):")
    for s in sessions:
        print(f"    {s['session_id'][:8]}... | {s['title']} | {s['updated_at']}")

    # 删除会话
    delete_session(sid)
    print(f"  删除后会话数: {len(list_sessions())}")

    print("✅ 测试完成！")
