# Python、FastAPI 与异步编程全解

## 1. 为什么使用 Python

Python 的模型 SDK、文档解析、Embedding、RAG、Agent 编排和评测生态完整，适合快速验证 AI 应用。项目 1 使用 Python 模块化单体，可以减少 Java/Python 跨服务通信和部署成本，把精力集中在知识源同步与 Agent 效果上。

收益：开发快、库丰富、类型标注可改善可维护性。代价：纯 CPU 计算性能不如编译型语言，动态类型容易把错误推迟到运行期，依赖和异步代码管理不当会产生线上问题。

解决方式：使用类型标注、Pydantic、静态检查、pytest；CPU 密集任务放进进程池或独立 Worker，I/O 密集任务使用异步并发。

## 2. GIL、线程、进程与协程

CPython 的 GIL 保证同一进程内同一时刻通常只有一个线程执行 Python 字节码。它不代表 Python 线程完全不能并发：线程在等待网络、磁盘等 I/O 时会释放 GIL，因此适合阻塞 I/O；CPU 密集型任务使用多进程或原生扩展。

协程由事件循环在单线程内调度。`await` 遇到可等待 I/O 时主动让出执行权，事件循环可以处理其他请求。优势是大量网络等待场景下线程切换成本低；风险是任何同步阻塞调用都会阻塞整个事件循环。

项目应用：模型 API、Embedding API、网页抓取、异步数据库属于 I/O 密集，可使用 `async/await`。PDF 解析、大文本分词若明显占 CPU，不应直接运行在事件循环中。

常见问题：

- 在 `async def` 中使用 `requests` 或同步数据库驱动：改为 `httpx.AsyncClient` 和异步驱动，或放入线程池。
- 无限制 `asyncio.gather`：使用 Semaphore 限制并发，防止模型 429、连接池耗尽和内存上涨。
- 忘记 `await`：开启类型检查和 asyncio debug，测试协程结果。
- 后台协程未保存引用：进程退出或异常无人处理。重要任务必须持久化任务状态，不能只用 `create_task`。

## 3. FastAPI 为什么适合项目

FastAPI 基于 ASGI，天然支持异步请求、SSE 和 WebSocket；结合 Pydantic 自动完成数据校验和 OpenAPI 文档。相比 Flask 的传统 WSGI 模型，更适合长连接与大量外部 API 等待。

项目结构中路由只做鉴权、参数校验和调用应用服务。业务逻辑放在 `knowledge_base`、`ingestion`、`retrieval`、`agent` 等模块，避免路由函数变成不可测试的大方法。

依赖注入 `Depends` 用于数据库 Session、当前用户、配置和限流器。其原理是 FastAPI 根据依赖图递归解析参数，并管理 `yield` 依赖的清理逻辑。不要把可变的用户状态存进全局单例依赖。

## 4. Pydantic 的作用

Pydantic 根据类型标注完成解析、校验和序列化。项目中请求 DTO、响应 DTO、配置项和内部任务消息都应使用明确模型，防止字典字段拼错和数据越界。

实体 ORM 模型与 API Schema 应分离：数据库字段变化不应自动暴露给外部；密码哈希、内部状态和错误详情不能进入普通响应。校验包括 URL 协议白名单、文件大小、分页上限、Top-K 范围和同步周期下限。

常见问题：过度使用可选字段导致校验失效；直接返回 ORM 对象泄露字段；对超大 JSON 一次解析造成内存峰值。解决方式是严格 Schema、显式响应模型和上传/响应大小限制。

## 5. SSE 原理与实际使用

SSE 是服务器通过一个 HTTP 响应持续发送文本事件，响应类型为 `text/event-stream`。浏览器原生支持自动重连，协议比 WebSocket 简单，适合“客户端提问、服务端单向流式回答”。

事件建议包含 `metadata`、`delta`、`citation`、`usage`、`done` 和 `error`。每条事件以空行分隔。FastAPI 使用异步生成器逐步 yield；客户端断开时应取消上游模型流并释放连接。

常见问题与解决：

- Nginx 缓冲导致前端一次收到全部内容：SSE 路径关闭 `proxy_buffering`。
- 心跳缺失被代理断开：定期发送注释或 heartbeat。
- 模型中断导致消息半成品：消息状态保存为 `GENERATING/COMPLETED/FAILED/CANCELLED`。
- 客户端重连造成重复提问：使用 message/request ID 做幂等，不盲目自动重放生成请求。

## 6. 面试高频问答

**异步一定更快吗？** 不一定。它提高 I/O 等待期间的并发利用率，不会加速 CPU 计算；低并发场景还会增加复杂度。

**FastAPI 的 async 路由能否调用同步函数？** 可以，但同步阻塞函数会阻塞事件循环；普通同步路由通常由线程池执行，关键是明确依赖是否阻塞。

**SSE 和 WebSocket 如何选择？** SSE 是 HTTP 上的服务端单向事件流，简单且适合模型输出；WebSocket 全双工，适合即时通信和高频双向交互。项目 1 用 SSE，项目 2 用 WebSocket。

**如何防止 Python 动态类型导致线上错误？** Pydantic 运行时校验、完整类型标注、mypy/pyright、单元和集成测试，并控制字典式跨层传递。
