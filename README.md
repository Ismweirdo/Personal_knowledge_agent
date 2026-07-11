# Personal Knowledge Agent

基于 FastAPI 的个人知识库问答 Agent。项目采用模块化单体结构，规划支持文档同步、RAG 检索、带引用的流式问答和离线评测。

## 当前状态

当前仓库提供 M1 工程骨架：应用启动、配置加载、统一错误结构、健康检查、测试和 Docker Compose 基础设施。知识库、入库、检索和 Agent 等目录已按设计文档划分，业务能力将在后续里程碑实现。

## 本地启动

要求 Python 3.12+。

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

访问 `http://localhost:8000/health` 或 `http://localhost:8000/docs`。

## 测试

```bash
cd backend
pytest
ruff check .
```

所有后续功能从 `main` 创建独立分支，经测试、Pull Request 和 Review 后合并。

## Docker Compose

复制 `.env.example` 为 `.env` 并替换密钥占位符，然后执行：

```bash
docker compose -f deploy/docker-compose.yml up --build
```

应用通过 `http://localhost:8080` 访问。详细方案见 [项目设计文档](docs/项目1设计文档.md) 和 [技术文档](docs/项目1技术文档.md)。
