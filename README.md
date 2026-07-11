# Personal Learning Knowledge Agent

基于 FastAPI 的持续学习型个人知识库与知识图谱 Agent。系统从文档、网页、项目和学习记录中增量吸收内容，同时维护可追溯的原文知识库和结构化知识图谱，用于问答、关联发现、知识缺口分析和复习规划。

## 当前状态

当前已具备工程基础、DeepSeek 客户端、用户认证和知识库生命周期。后续里程碑将依次实现增量入库、RAG 引用问答、实体关系抽取、学习事件与审核闭环。

开发环境默认通过 OpenAI 兼容协议接入 DeepSeek，默认模型为 `deepseek-chat`。真实 API Key 仅通过本地 `.env` 的 `LLM_API_KEY` 注入，禁止提交到仓库。私人简历、学习笔记、项目源码与上传文件同样不得提交到公开仓库。

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
