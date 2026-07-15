# Personal Learning Knowledge Agent

基于 FastAPI 的“个人 Agent”。管理员持续导入自己的文档、项目和学习记录；普通用户只能与该 Agent 对话，不能创建自己的知识库、上传资料或修改 Agent 知识。

系统区分管理员端和用户端：管理员端负责知识源、索引、候选知识侧边审核、访客评论和发布；用户端不注册账号，只输入站点密钥进入对话，使用独立访客身份管理自己的会话、流式问答、引用查看与岗位建议评论。

## 当前状态

当前已具备管理员/访客双端、批量文件上传、文件/网页/Git 分类来源列表、来源更新删除、持久化后台任务、GitHub Models Embedding、pgvector 检索、DeepSeek SSE 问答、候选知识侧边审核、CI、可观测与部署基础。上传或同步完成解析后创建任务，Worker 自动完成 Embedding 和活动版本切换；候选知识抽取作为增强步骤执行，失败或跳过不影响问答知识先可用。

当前问答链路对项目、技能和岗位类问题优先使用按来源均衡的结构化快速检索，保证简历和各项目仓库共同提供证据；其他问题使用 pgvector 检索。没有证据时直接拒答，不调用模型补全。DeepSeek 增量通过 SSE 到达浏览器，前端使用安全清洗后的 Markdown 渲染并逐帧显示。知识图谱可视化、学习复习和复杂关系推理暂时搁置到后续版本，当前不占用管理端主界面。

导入链路已增加基础清洗：PDF/Markdown/TXT 会清理页码、重复空白和重复行；Git 项目支持本地允许目录或 GitHub 仓库 URL，导入时优先保留 README、设计/技术文档、配置摘要和代码结构摘要，过滤依赖、测试、构建产物、密钥文件和泛化学习资料，避免把无关源码噪声直接暴露给访客问答。

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

Compose 默认启动后台入库 Worker，并将当前项目目录以只读方式挂载到容器内 `/app/git-imports`，用于本地 Git 项目同步。以当前开发目录为例，管理员端“同步 Git 项目”可填写：

```text
/app/git-imports
```

如果要缩小或更换可导入范围，在 `.env` 中修改：

```env
GIT_IMPORT_HOST_ROOT=..
GIT_IMPORT_ROOT=/app/git-imports
BACKGROUND_WORKER_ENABLED=true
```

其中 `GIT_IMPORT_HOST_ROOT` 是宿主机路径，`GIT_IMPORT_ROOT` 是容器内路径；后端只允许同步 `GIT_IMPORT_ROOT` 内的文本项目文件，并排除 `.env*`、`.git`、依赖目录和构建产物。也可以直接填写公开 GitHub 仓库地址，例如 `https://github.com/owner/repo`；复制到的 `.git`、`/tree/分支/...`、省略协议或 GitHub SSH 地址会统一转换为 HTTPS 仓库地址。私有仓库当前不接收访问令牌。为了避免误扫密钥文件，不建议把包含令牌、桌面资料或下载目录的上级目录整体挂载进容器；需要导入其他本地项目时，把 `GIT_IMPORT_HOST_ROOT` 临时改为那个项目目录。若入库任务一直停在 `PENDING · 0%`，优先确认 `BACKGROUND_WORKER_ENABLED=true` 且后端容器已重启。

## 文档

- [项目设计文档](docs/项目1设计文档.md)：产品边界、架构、数据模型和里程碑。
- [项目技术文档](docs/项目1技术文档.md)：工程结构、API、入库、RAG、安全、测试与部署。
- [管理员使用说明](docs/管理员使用说明.md)：管理员登录、知识维护、发布、侧边候选审核和 HR 评论查看。
- [开发文档](docs/开发文档.md)：开发过程中遇到的问题、根因、解决方法、选择理由和剩余风险。
- [持续学习与知识图谱设计](docs/持续学习与知识图谱设计.md)：证据、审核、冲突和学习闭环。
- [验证与评测说明](docs/验证与评测说明.md)：自动化、真实依赖、效果评测和压测边界。
- [上线运行手册](docs/上线运行手册.md)：生产配置、健康检查、备份恢复和故障处理。
