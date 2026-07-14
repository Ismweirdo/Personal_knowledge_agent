# Personal Learning Knowledge Agent

基于 FastAPI 的“个人 Agent”。管理员持续导入自己的文档、项目和学习记录；普通用户只能与该 Agent 对话，不能创建自己的知识库、上传资料或修改 Agent 知识。

系统区分管理员端和用户端：管理员端负责知识源、索引、图谱审核、访客评论和发布；用户端不注册账号，只输入站点密钥进入对话，使用独立访客身份管理自己的会话、流式问答、引用查看与岗位建议评论。

## 当前状态

当前已具备管理员/访客双端、文件/网页/Git 增量同步、持久化后台任务、GitHub Models Embedding、pgvector 检索、DeepSeek SSE 问答、证据化知识图谱、候选审核、学习复习、CI、可观测与部署基础。上传或同步完成解析后创建任务，Worker 自动完成 Embedding、活动版本切换和图谱候选抽取，管理员前端轮询进度。

当前问答链路使用 pgvector 余弦 Top-K 检索、来源引用和资料不足拒答 Prompt；知识图谱用于证据抽取、候选审核、修订和复习任务，尚未并入问答检索。混合检索、Reranker、Query Rewrite 和通用工具调用属于后续评测驱动的优化，不是当前已完成功能。

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

开发环境可使用 GitHub Models 的 OpenAI 兼容 Embedding 接口：

```env
EMBEDDING_BASE_URL=https://models.github.ai/inference
EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
EMBEDDING_API_KEY=your-fine-grained-token
BACKGROUND_WORKER_ENABLED=true
ADMIN_USERNAME=your-admin-name
ADMIN_PASSWORD=your-admin-password
VISITOR_ACCESS_KEY=your-visitor-access-key
```

## 测试

```bash
cd backend
pytest
ruff check .
```

所有后续功能从 `main` 创建独立分支，经测试、Pull Request 和 Review 后合并。

## 初始化访问入口

前端不再开放注册。管理员登录入口位于右上角，账号和密码通过 `.env` 的 `ADMIN_USERNAME`、`ADMIN_PASSWORD` 注入；访客使用 `VISITOR_ACCESS_KEY` 获取独立访客 Token 后进入对话界面。旧的交互式管理员初始化命令仍可作为维护工具使用：

```bash
cd backend
python -m app.infrastructure.bootstrap_admin your-email@example.com
```

## Docker Compose

复制 `.env.example` 为 `.env` 并替换密钥占位符，然后执行：

```bash
docker compose -f deploy/docker-compose.yml up --build
```

应用通过 `http://localhost:8080` 访问。

## 文档

- [项目设计文档](docs/项目1设计文档.md)：产品边界、架构、数据模型和里程碑。
- [项目技术文档](docs/项目1技术文档.md)：工程结构、API、入库、RAG、安全、测试与部署。
- [管理员使用说明](docs/管理员使用说明.md)：管理员登录、知识维护、发布、审核、复习和 HR 评论查看。
- [开发文档](docs/开发文档.md)：开发过程中遇到的问题、根因、解决方法、选择理由和剩余风险。
- [持续学习与知识图谱设计](docs/持续学习与知识图谱设计.md)：证据、审核、冲突和学习闭环。
- [验证与评测说明](docs/验证与评测说明.md)：自动化、真实依赖、效果评测和压测边界。
- [上线运行手册](docs/上线运行手册.md)：生产配置、健康检查、备份恢复和故障处理。
