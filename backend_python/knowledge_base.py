import os

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import chromadb
from sentence_transformers import SentenceTransformer

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
BGE_MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# 优先级：1. 本地硬路径（你现有的图标位置） 2. 项目内 models 文件夹 3. 自动下载
BGE_MODEL_PATH = os.path.join(PROJECT_ROOT, "models--BAAI--bge-small-zh-v1.5")
if not os.path.exists(BGE_MODEL_PATH):
    BGE_MODEL_PATH = BGE_MODEL_NAME

print(f"⏳ 正在加载 BGE 向量模型 ({BGE_MODEL_NAME})...")
_embedding_model = None
_client = None
_collection = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        # 显式指定项目内的 models 文件夹作为下载缓存，防止存入 C 盘
        _embedding_model = SentenceTransformer(BGE_MODEL_PATH, cache_folder=MODELS_DIR)
        print(f"✅ BGE 模型加载完毕: {BGE_MODEL_PATH}")
    return _embedding_model


def _get_collection():
    global _client, _collection
    if _collection is None:
        # 确保 ChromaDB 的存储目录也存在
        if not os.path.exists(CHROMA_DB_PATH):
            os.makedirs(CHROMA_DB_PATH, exist_ok=True)
            
        _client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        print(f"✅ ChromaDB 集合就绪: {COLLECTION_NAME} (数据目录: {CHROMA_DB_PATH})")
        print(f"   当前知识库条目数: {_collection.count()}")
    return _collection


def add_to_kb(text_list):
    """将文本列表编码后存入 ChromaDB 知识库"""
    if not text_list or len(text_list) == 0:
        return 0

    collection = _get_collection()
    model = _get_embedding_model()

    ids = [f"doc_{i}_{hash(text)}" for i, text in enumerate(text_list)]
    embeddings = model.encode(text_list).tolist()

    existing_ids = set(collection.get(ids=ids)["ids"]) if ids else set()
    new_ids = [idx for idx in ids if idx not in existing_ids]
    new_texts = [text for idx, text in zip(ids, text_list) if idx not in existing_ids]
    new_embeddings = [emb for idx, emb in zip(ids, embeddings) if idx not in existing_ids]

    if new_ids:
        collection.add(
            ids=new_ids,
            documents=new_texts,
            embeddings=new_embeddings
        )
        print(f"📚 知识库新增 {len(new_ids)} 条条目，当前总计: {collection.count()}")
    else:
        print(f"📚 所有条目已存在，无需重复添加。")

    return collection.count()


def query_kb(query_text, n_results=1):
    """在知识库中检索与查询最相关的文本段落"""
    collection = _get_collection()
    model = _get_embedding_model()

    if collection.count() == 0:
        return []

    query_embedding = model.encode([query_text]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(n_results, collection.count())
    )

    retrieved = []
    if results and results.get("documents"):
        for doc_list in results["documents"]:
            for doc in doc_list:
                retrieved.append(doc)

    print(f"🔍 知识库检索: 查询='{query_text[:50]}...' → 命中 {len(retrieved)} 条")
    return retrieved


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  📖 RAG 知识库模块测试")
    print("=" * 50)

    sample_docs = [
        "牛顿第二定律：物体的加速度与所受合外力成正比，与质量成反比，公式为 F=ma。",
        "光合作用是绿色植物利用叶绿素，将二氧化碳和水转化为有机物并释放氧气的过程。",
        "李白（701年－762年），字太白，号青莲居士，唐代浪漫主义诗人，被后人誉为诗仙。",
        "细胞是生物体基本的结构和功能单位，由细胞膜、细胞质和细胞核组成。"
    ]

    print("\n>>> 写入测试样本...")
    total = add_to_kb(sample_docs)
    print(f"\n>>> 检索测试 1: '牛顿定律'")
    r1 = query_kb("牛顿定律", n_results=2)
    for item in r1:
        print(f"   → {item[:80]}...")

    print("\n>>> 检索测试 2: '诗人李白'")
    r2 = query_kb("诗人李白", n_results=1)
    for item in r2:
        print(f"   → {item[:80]}...")

    print("\n" + "=" * 50)
    print("  🏁 知识库测试完成")
    print("=" * 50)
