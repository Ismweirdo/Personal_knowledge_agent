<script setup>
import DOMPurify from "dompurify";
import { marked } from "marked";
import { computed, nextTick, onMounted, ref } from "vue";
import {
  BookOpen,
  Brain,
  FileUp,
  GitBranch,
  LogOut,
  MessageSquare,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Trash2,
} from "@lucide/vue";
import { api, stream, token } from "./api";

const user = ref(null);
const loginView = ref("visitor");
const accessKey = ref("");
const adminUsername = ref("");
const adminPassword = ref("");
const error = ref("");
const busy = ref(false);

const agent = ref(null);
const conversations = ref([]);
const conversation = ref(null);
const question = ref("");
const messages = ref([]);
const messagesPanel = ref(null);
const citations = ref([]);
const feedbackPosition = ref("");
const feedbackComment = ref("");
const feedbackNotice = ref("");
const suggestedQuestions = [
  "你掌握了哪些技术栈？",
  "你做过哪些项目？",
  "你的项目中有哪些亮点？",
  "你适合什么岗位？",
];

const tab = ref("knowledge");
const knowledgeBases = ref([]);
const selectedKb = ref("");
const webUrl = ref("");
const gitPath = ref("");
const sources = ref([]);
const sourceTab = ref("FILE");
const pendingFiles = ref([]);
const selectedFileSourceIds = ref([]);
const fileInput = ref(null);
const candidates = ref({ entities: [], relations: [] });
const graphData = ref({ nodes: [], edges: [] });
const reviews = ref([]);
const visitorFeedback = ref([]);
const notice = ref("");

const isAdmin = computed(() => user.value?.role === "ADMIN");
const activeKb = computed(() =>
  knowledgeBases.value.find((item) => item.id === selectedKb.value),
);
const sourceTabs = [
  { type: "FILE", label: "文件" },
  { type: "WEB", label: "网页" },
  { type: "GIT", label: "Git 项目" },
];
const visibleSources = computed(() =>
  sources.value.filter((item) => item.source_type === sourceTab.value),
);
const allVisibleFilesSelected = computed(
  () =>
    visibleSources.value.length > 0 &&
    visibleSources.value.every((item) =>
      selectedFileSourceIds.value.includes(item.id),
    ),
);
const graphNodes = computed(() => {
  const total = Math.max(graphData.value.nodes.length, 1);
  const cx = 360;
  const cy = 190;
  const radius = total > 8 ? 145 : 115;
  return graphData.value.nodes.map((node, index) => {
    const angle = (Math.PI * 2 * index) / total - Math.PI / 2;
    return {
      ...node,
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    };
  });
});
const graphNodeById = computed(() =>
  Object.fromEntries(graphNodes.value.map((node) => [node.id, node])),
);

marked.use({ breaks: true, gfm: true });

function renderMarkdown(content) {
  return DOMPurify.sanitize(marked.parse(content || ""));
}

let pendingScrollFrame = null;
function scrollMessagesToBottom() {
  if (pendingScrollFrame !== null) return;
  pendingScrollFrame = requestAnimationFrame(async () => {
    pendingScrollFrame = null;
    await nextTick();
    const panel = messagesPanel.value;
    if (panel) panel.scrollTop = panel.scrollHeight;
  });
}

async function loadUser() {
  if (!token.get()) return;
  try {
    user.value = await api("/auth/me");
    await afterLogin();
  } catch {
    token.set(null);
  }
}

async function visitorAccess() {
  busy.value = true;
  error.value = "";
  try {
    const data = await api("/auth/access", {
      method: "POST",
      body: JSON.stringify({ access_key: accessKey.value }),
    });
    token.set(data.access_token);
    user.value = await api("/auth/me");
    await afterLogin();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function adminLogin() {
  busy.value = true;
  error.value = "";
  try {
    const data = await api("/auth/admin/login", {
      method: "POST",
      body: JSON.stringify({
        username: adminUsername.value,
        password: adminPassword.value,
      }),
    });
    token.set(data.access_token);
    user.value = await api("/auth/me");
    await afterLogin();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function afterLogin() {
  if (isAdmin.value) await loadAdmin();
  else {
    agent.value = await api("/agent");
    await loadConversations();
    await loadFeedback();
  }
}

function logout() {
  token.set(null);
  user.value = null;
  agent.value = null;
  conversations.value = [];
  conversation.value = null;
  messages.value = [];
  citations.value = [];
  error.value = "";
  feedbackNotice.value = "";
}

async function loadConversations() {
  conversations.value = await api("/conversations");
  if (!conversation.value && conversations.value.length) {
    await openConversation(conversations.value[0]);
  }
}

async function openConversation(item) {
  conversation.value = item;
  citations.value = [];
  messages.value = await api(`/conversations/${item.id}/messages`);
}

function newConversation() {
  conversation.value = null;
  messages.value = [];
  citations.value = [];
  question.value = "";
}

async function deleteConversation(item) {
  if (!item) return;
  await api(`/conversations/${item.id}`, { method: "DELETE" });
  if (conversation.value?.id === item.id) newConversation();
  await loadConversations();
}

async function ask() {
  if (!question.value.trim() || busy.value) return;
  busy.value = true;
  const text = question.value.trim();
  question.value = "";
  messages.value.push({ role: "user", content: text });
  const replyIndex =
    messages.value.push({ role: "assistant", content: "", streaming: true }) -
    1;
  const pendingDeltas = [];
  let deltaFrame = null;
  let streamFinished = false;
  let failureMessage = "";
  let resolveRendered;
  const rendered = new Promise((resolve) => {
    resolveRendered = resolve;
  });
  const finishRendering = () => {
    if (streamFinished && !pendingDeltas.length) resolveRendered();
  };
  const renderNextDelta = () => {
    deltaFrame = null;
    const delta = pendingDeltas.shift();
    if (delta) {
      const currentReply = messages.value[replyIndex];
      messages.value[replyIndex] = {
        ...currentReply,
        content: currentReply.content + delta,
      };
      scrollMessagesToBottom();
    }
    if (pendingDeltas.length) {
      deltaFrame = requestAnimationFrame(renderNextDelta);
    } else {
      finishRendering();
    }
  };
  const enqueueDelta = (value) => {
    const characters = Array.from(value || "");
    for (let index = 0; index < characters.length; index += 8) {
      pendingDeltas.push(characters.slice(index, index + 8).join(""));
    }
    if (deltaFrame === null && pendingDeltas.length) {
      deltaFrame = requestAnimationFrame(renderNextDelta);
    }
  };
  scrollMessagesToBottom();
  try {
    if (!conversation.value) {
      conversation.value = await api("/conversations", {
        method: "POST",
        body: JSON.stringify({
          knowledge_base_id: agent.value.knowledgeBaseId,
          title: text.slice(0, 80),
        }),
      });
      await loadConversations();
    }
    await stream(
      `/conversations/${conversation.value.id}/messages:stream`,
      { content: text },
      (type, data) => {
        if (type === "delta") enqueueDelta(data.text);
        if (type === "citation") citations.value = data;
        if (type === "error") {
          failureMessage = "当前知识库证据不足，暂时无法回答。";
        }
      },
    );
  } catch (e) {
    failureMessage = e.message;
  } finally {
    streamFinished = true;
    finishRendering();
    await rendered;
    if (failureMessage && !messages.value[replyIndex].content) {
      messages.value[replyIndex].content = failureMessage;
    }
    messages.value[replyIndex].streaming = false;
    busy.value = false;
    scrollMessagesToBottom();
  }
}

function submitOnEnter(event) {
  if (event.isComposing) return;
  if (event.shiftKey) return;
  event.preventDefault();
  ask();
}

function askSuggestion(text) {
  if (busy.value) return;
  question.value = text;
  ask();
}

async function submitFeedback() {
  if (!feedbackPosition.value.trim() || !feedbackComment.value.trim()) return;
  await api("/conversations/feedback", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: conversation.value?.id || null,
      position: feedbackPosition.value.trim(),
      comment: feedbackComment.value.trim(),
    }),
  });
  feedbackPosition.value = "";
  feedbackComment.value = "";
  feedbackNotice.value = "已收到，谢谢你的建议。";
  await loadFeedback();
}

async function loadFeedback() {
  visitorFeedback.value = await api("/conversations/feedback");
}

async function loadAdmin() {
  knowledgeBases.value = await api("/knowledge-bases");
  selectedKb.value ||= knowledgeBases.value[0]?.id || "";
  if (selectedKb.value) {
    [candidates.value, graphData.value, sources.value] = await Promise.all([
      api(`/knowledge-bases/${selectedKb.value}/knowledge-candidates`),
      api(`/knowledge-bases/${selectedKb.value}/graph`),
      api(`/knowledge-bases/${selectedKb.value}/sources`),
    ]);
    selectedFileSourceIds.value = selectedFileSourceIds.value.filter((id) =>
      sources.value.some(
        (item) => item.id === id && item.source_type === "FILE",
      ),
    );
  } else {
    sources.value = [];
  }
  reviews.value = await api("/admin/learning/review-tasks?include_future=true");
  visitorFeedback.value = await api("/conversations/feedback");
}

async function clearKnowledge() {
  if (!selectedKb.value) return;
  const ok = confirm(
    "确定清空当前知识库的所有导入内容、Chunk、向量和知识图谱吗？知识库本身会保留。",
  );
  if (!ok) return;
  const result = await api(`/knowledge-bases/${selectedKb.value}/contents`, {
    method: "DELETE",
  });
  notice.value = `已清空：${result.sources} 个来源、${result.chunks} 个分块、${result.entities} 个实体、${result.relations} 条关系。`;
  candidates.value = { entities: [], relations: [] };
  graphData.value = { nodes: [], edges: [] };
  await loadAdmin();
}

async function createKb() {
  const name = prompt("请输入知识库名称");
  if (!name) return;
  await api("/knowledge-bases", {
    method: "POST",
    body: JSON.stringify({ name, is_published: false }),
  });
  await loadAdmin();
}

async function publish(kb) {
  if (!kb) return;
  await api(`/knowledge-bases/${kb.id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_published: !kb.is_published }),
  });
  await loadAdmin();
}

function selectFiles(event) {
  pendingFiles.value = Array.from(event.target.files || []);
  if (pendingFiles.value.length > 20) {
    notice.value = "一次最多选择 20 个文件，请减少后重试。";
  }
}

async function uploadFiles() {
  if (!pendingFiles.value.length || !selectedKb.value || busy.value) return;
  const body = new FormData();
  pendingFiles.value.forEach((file) => body.append("files", file));
  busy.value = true;
  notice.value = `正在解析 ${pendingFiles.value.length} 个文件...`;
  try {
    const result = await api(
      `/knowledge-bases/${selectedKb.value}/documents:batch`,
      { method: "POST", body },
    );
    const failedNames = result.items
      .filter((item) => !item.success)
      .map((item) => item.filename);
    notice.value = `批量导入完成：成功 ${result.succeeded} 个，失败 ${result.failed} 个${
      failedNames.length ? `（${failedNames.join("、")}）` : ""
    }。`;
    const taskIds = result.items
      .filter((item) => item.success && item.result?.task_id)
      .map((item) => item.result.task_id);
    pendingFiles.value = [];
    if (fileInput.value) fileInput.value.value = "";
    await loadAdmin();
    if (taskIds.length) void trackTasks(taskIds);
  } catch (e) {
    notice.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function syncSource(type) {
  if (!selectedKb.value) {
    notice.value = "请先新建或选择一个知识库。";
    return;
  }
  if (type === "web" && !webUrl.value.trim()) {
    notice.value = "请先填写网页地址。";
    return;
  }
  if (type === "git" && !gitPath.value.trim()) {
    notice.value = "请先填写 Git 项目路径。";
    return;
  }
  const payload =
    type === "web"
      ? { url: webUrl.value.trim() }
      : { repository_path: gitPath.value.trim() };
  busy.value = true;
  notice.value = type === "web" ? "正在同步网页..." : "正在同步 Git 项目...";
  try {
    const result = await api(
      `/knowledge-bases/${selectedKb.value}/sources:${type}`,
      { method: "POST", body: JSON.stringify(payload) },
    );
    notice.value = result.unchanged
      ? "知识源未变化"
      : `已创建 ${result.chunk_count} 个分块，后台任务已入队`;
    if (result.task_id) trackTask(result.task_id);
  } catch (e) {
    notice.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function refreshSource(source) {
  if (!selectedKb.value || busy.value) return;
  busy.value = true;
  notice.value = `正在更新 ${source.display_name}...`;
  try {
    const result = await api(
      `/knowledge-bases/${selectedKb.value}/sources/${source.id}:sync`,
      { method: "POST", body: "{}" },
    );
    notice.value = result.unchanged
      ? `${source.display_name} 没有变化。`
      : `${source.display_name} 已创建新版本，正在入库。`;
    await loadAdmin();
    if (result.task_id) void trackTask(result.task_id);
  } catch (e) {
    notice.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function deleteSource(source) {
  if (!confirm(`确定删除“${source.display_name}”及其全部版本和检索内容吗？`))
    return;
  busy.value = true;
  try {
    await api(`/knowledge-bases/${selectedKb.value}/sources/${source.id}`, {
      method: "DELETE",
    });
    notice.value = `已删除 ${source.display_name}。`;
    selectedFileSourceIds.value = selectedFileSourceIds.value.filter(
      (id) => id !== source.id,
    );
    await loadAdmin();
  } catch (e) {
    notice.value = e.message;
  } finally {
    busy.value = false;
  }
}

function toggleAllFiles() {
  selectedFileSourceIds.value = allVisibleFilesSelected.value
    ? []
    : visibleSources.value.map((item) => item.id);
}

async function deleteSelectedFiles() {
  const selected = sources.value.filter((item) =>
    selectedFileSourceIds.value.includes(item.id),
  );
  if (!selected.length) return;
  if (!confirm(`确定删除选中的 ${selected.length} 个文件及其全部知识内容吗？`))
    return;
  busy.value = true;
  const results = await Promise.allSettled(
    selected.map((item) =>
      api(`/knowledge-bases/${selectedKb.value}/sources/${item.id}`, {
        method: "DELETE",
      }),
    ),
  );
  const failed = results.filter((item) => item.status === "rejected").length;
  notice.value = `批量删除完成：成功 ${results.length - failed} 个，失败 ${failed} 个。`;
  selectedFileSourceIds.value = [];
  busy.value = false;
  await loadAdmin();
}

function sourceCount(type) {
  return sources.value.filter((item) => item.source_type === type).length;
}

function sourceStatus(source) {
  const status =
    source.task_status || source.latest_version_status || source.status;
  const labels = {
    PENDING: "等待入库",
    RUNNING: `入库中 ${source.task_progress || 0}%`,
    RETRY_WAIT: "等待重试",
    FAILED: "入库失败",
    PARSED: "已解析",
    INDEXING: "索引中",
    READY: "可用于问答",
    SUCCEEDED: "可用于问答",
    PROCESSING: "处理中",
  };
  return labels[status] || status || "未知";
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "尚未入库";
}

async function trackTasks(taskIds) {
  const ids = [...new Set(taskIds)];
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const tasks = await Promise.all(ids.map((id) => api(`/admin/tasks/${id}`)));
    const finished = tasks.filter((task) =>
      ["SUCCEEDED", "FAILED"].includes(task.status),
    ).length;
    const average = Math.round(
      tasks.reduce((sum, task) => sum + task.progress, 0) / tasks.length,
    );
    notice.value = `批量入库 ${finished}/${tasks.length} · 平均进度 ${average}%`;
    if (finished === tasks.length) {
      const failed = tasks.filter((task) => task.status === "FAILED").length;
      notice.value = `批量入库完成：成功 ${tasks.length - failed} 个，失败 ${failed} 个。`;
      await loadAdmin();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  notice.value = "部分入库任务仍在运行，可在来源列表查看状态。";
}

async function trackTask(taskId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const task = await api(`/admin/tasks/${taskId}`);
    notice.value = `入库任务 ${task.status} · ${task.progress}%`;
    if (task.status === "SUCCEEDED") {
      if (task.errorCode || task.error_code) {
        notice.value =
          "问答知识已入库完成，图谱候选抽取部分跳过或失败，可稍后手动补充审核。";
      } else {
        notice.value = "入库完成，问答知识和候选知识已更新。";
      }
      await loadAdmin();
      return;
    }
    if (task.status === "FAILED") {
      notice.value = `入库失败：${task.error_message || task.error_code}`;
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  notice.value = "入库仍在运行，可稍后查看任务状态。";
}

async function review(type, id, action) {
  await api(`/knowledge-candidates/${type}/${id}:${action}`, {
    method: "POST",
    body: "{}",
  });
  await loadAdmin();
}

async function grade(entityId, gradeValue) {
  await api(`/admin/learning/entities/${entityId}/review`, {
    method: "POST",
    body: JSON.stringify({ grade: gradeValue }),
  });
  await loadAdmin();
}

onMounted(loadUser);
</script>

<template>
  <main v-if="!user" class="auth-shell">
    <button
      class="admin-entry"
      @click="loginView = loginView === 'admin' ? 'visitor' : 'admin'"
    >
      <ShieldCheck :size="16" />
      {{ loginView === "admin" ? "访客进入" : "管理员登录" }}
    </button>
    <section class="auth-panel">
      <div class="bear-hero" aria-hidden="true">
        <div class="bear-blob">
          <span class="ear left"></span><span class="ear right"></span>
          <span class="eye left"></span><span class="eye right"></span>
          <span class="nose"></span><span class="paw left"></span
          ><span class="paw right"></span>
        </div>
        <div class="lamp"></div>
      </div>
      <div class="brand"><Brain :size="28" /><span>求职学习 Agent</span></div>
      <template v-if="loginView === 'visitor'">
        <h1>输入密钥进入对话</h1>
        <p>与我的个人知识库求职学习 Agent 对话。</p>
        <form @submit.prevent="visitorAccess">
          <label
            >访问密钥<input v-model="accessKey" type="password" required
          /></label>
          <p v-if="error" class="error">{{ error }}</p>
          <button :disabled="busy">{{ busy ? "进入中" : "进入网站" }}</button>
        </form>
      </template>
      <template v-else>
        <h1>管理员登录</h1>
        <p>管理知识库、学习任务和访客反馈。</p>
        <form @submit.prevent="adminLogin">
          <label
            >账号<input
              v-model="adminUsername"
              autocomplete="username"
              required
          /></label>
          <label
            >密码<input v-model="adminPassword" type="password" required
          /></label>
          <p v-if="error" class="error">{{ error }}</p>
          <button :disabled="busy">{{ busy ? "登录中" : "登录管理端" }}</button>
        </form>
      </template>
    </section>
  </main>

  <div v-else class="app-shell">
    <aside>
      <div class="brand"><Brain :size="24" /><span>求职学习 Agent</span></div>
      <nav v-if="isAdmin">
        <button
          :class="{ active: tab === 'knowledge' }"
          @click="tab = 'knowledge'"
        >
          <BookOpen />知识库
        </button>
        <button :class="{ active: tab === 'review' }" @click="tab = 'review'">
          <RefreshCw />复习
        </button>
        <button :class="{ active: tab === 'graph' }" @click="tab = 'graph'">
          <Brain />图谱
        </button>
        <button
          :class="{ active: tab === 'feedback' }"
          @click="tab = 'feedback'"
        >
          <MessageSquare />评论
        </button>
      </nav>
      <nav v-else>
        <button class="active"><MessageSquare />对话</button>
      </nav>
      <div class="account">
        <ShieldCheck v-if="isAdmin" />
        <span
          >{{ isAdmin ? "管理员" : "访客"
          }}<small>{{ user.email }}</small></span
        >
        <button title="退出" @click="logout"><LogOut /></button>
      </div>
    </aside>

    <section v-if="!isAdmin" class="chat-layout">
      <div class="conversation-sidebar">
        <button class="new-chat" @click="newConversation">
          <Plus :size="16" />新建对话
        </button>
        <button
          v-for="item in conversations"
          :key="item.id"
          class="conversation-item"
          :class="{ active: conversation?.id === item.id }"
          @click="openConversation(item)"
        >
          <span>{{ item.title }}</span>
          <Trash2
            :size="15"
            title="删除对话"
            @click.stop="deleteConversation(item)"
          />
        </button>
        <section class="sidebar-feedback">
          <h3>留言建议</h3>
          <form @submit.prevent="submitFeedback">
            <input
              v-model="feedbackPosition"
              placeholder="岗位，如：后端开发"
            />
            <textarea
              v-model="feedbackComment"
              rows="3"
              placeholder="写下你的建议"
            />
            <button :disabled="!feedbackPosition || !feedbackComment">
              发表评论
            </button>
            <small v-if="feedbackNotice">{{ feedbackNotice }}</small>
          </form>
          <div class="feedback-stream">
            <article v-for="item in visitorFeedback.slice(0, 6)" :key="item.id">
              <b>{{ item.position }}</b>
              <p>{{ item.comment }}</p>
            </article>
            <p v-if="!visitorFeedback.length" class="muted">
              还没有评论，欢迎留下第一条建议。
            </p>
          </div>
        </section>
      </div>
      <section class="chat">
        <header>
          <div>
            <h2>向我提几个问题吧</h2>
            <p>围绕我的技术栈、项目经历、岗位匹配和学习方向进行提问。</p>
            <div class="suggestions">
              <button
                v-for="item in suggestedQuestions"
                :key="item"
                type="button"
                @click="askSuggestion(item)"
              >
                {{ item }}
              </button>
            </div>
          </div>
          <div class="bear-blob chat-mascot" aria-hidden="true">
            <span class="ear left"></span><span class="ear right"></span>
            <span class="eye left"></span><span class="eye right"></span>
            <span class="nose"></span>
          </div>
        </header>
        <div ref="messagesPanel" class="messages" aria-live="polite">
          <div v-if="!messages.length" class="empty">
            <div class="bear-blob rest" aria-hidden="true">
              <span class="ear left"></span><span class="ear right"></span>
              <span class="eye left"></span><span class="eye right"></span>
              <span class="nose"></span><span class="paw left"></span
              ><span class="paw right"></span>
            </div>
            <h3>向我提几个问题吧</h3>
            <p>例如：你掌握了哪些技术栈？你做过哪些项目？</p>
          </div>
          <article
            v-for="(m, i) in messages"
            :key="m.id || i"
            :class="[m.role, { streaming: m.streaming }]"
          >
            <strong>{{ m.role === "user" ? "你" : "求职学习 Agent" }}</strong>
            <p v-if="m.role === 'user'" class="message-content user-content">
              {{ m.content }}
            </p>
            <div
              v-else
              class="message-content markdown-body"
              v-html="renderMarkdown(m.content)"
            ></div>
            <span
              v-if="m.streaming"
              class="streaming-cursor"
              aria-label="正在生成"
            ></span>
          </article>
          <div v-if="citations.length" class="sources compact">
            已参考 {{ citations.length }} 条知识资料
          </div>
        </div>
        <form class="composer" @submit.prevent="ask">
          <textarea
            v-model="question"
            placeholder="请输入问题，Enter 发送，Shift + Enter 换行"
            rows="2"
            @keydown.enter.exact="submitOnEnter"
          ></textarea>
          <button title="发送" :disabled="busy"><Send /></button>
        </form>
      </section>
    </section>

    <section v-else class="workspace">
      <header>
        <div>
          <h2>
            {{
              tab === "knowledge"
                ? "知识库管理"
                : tab === "review"
                  ? "学习复习"
                  : tab === "graph"
                    ? "知识图谱"
                    : "访客评论"
            }}
          </h2>
          <p>
            {{
              tab === "knowledge"
                ? "维护公开 Agent 背后的个人知识资产。"
                : tab === "review"
                  ? "按复习计划巩固已抽取的知识实体。"
                  : tab === "graph"
                    ? "查看项目、技能、经历之间的结构化关系。"
                    : "查看访客基于岗位给出的建议。"
            }}
          </p>
        </div>
        <button v-if="tab === 'knowledge'" @click="createKb">新建知识库</button>
      </header>

      <template v-if="tab === 'knowledge'">
        <div class="toolbar">
          <select v-model="selectedKb" @change="loadAdmin">
            <option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
              {{ kb.name }}
            </option>
          </select>
          <button
            v-if="knowledgeBases.length"
            class="secondary"
            @click="publish(activeKb)"
          >
            {{ activeKb?.is_published ? "取消发布" : "发布 Agent" }}
          </button>
          <button
            v-if="knowledgeBases.length"
            class="danger-button"
            @click="clearKnowledge"
          >
            清空内容
          </button>
        </div>
        <div class="admin-grid">
          <section>
            <h3><FileUp />导入文件</h3>
            <input
              ref="fileInput"
              type="file"
              accept=".pdf,.md,.txt"
              multiple
              @change="selectFiles"
            />
            <small>支持 PDF、Markdown、TXT，一次最多 20 个。</small>
            <button
              :disabled="
                busy ||
                !selectedKb ||
                !pendingFiles.length ||
                pendingFiles.length > 20
              "
              @click="uploadFiles"
            >
              <FileUp :size="16" />
              {{
                pendingFiles.length
                  ? `导入 ${pendingFiles.length} 个文件`
                  : "请选择文件"
              }}
            </button>
          </section>
          <section>
            <h3><BookOpen />同步网页</h3>
            <input v-model="webUrl" placeholder="https://example.com/notes" />
            <button
              :disabled="busy || !selectedKb || !webUrl.trim()"
              @click="syncSource('web')"
            >
              同步
            </button>
          </section>
          <section>
            <h3><GitBranch />同步 Git 项目</h3>
            <input
              v-model="gitPath"
              placeholder="/app/git-imports 或 https://github.com/owner/repo"
            />
            <button
              :disabled="busy || !selectedKb || !gitPath.trim()"
              @click="syncSource('git')"
            >
              同步
            </button>
          </section>
        </div>
        <p v-if="notice" class="notice">{{ notice }}</p>
        <section class="source-manager">
          <header>
            <div>
              <h3>已导入内容</h3>
              <p>查看当前知识库实际参与问答的文件、网页和 Git 项目。</p>
            </div>
            <button
              v-if="sourceTab === 'FILE' && selectedFileSourceIds.length"
              class="danger"
              :disabled="busy"
              @click="deleteSelectedFiles"
            >
              <Trash2 :size="15" />删除所选（{{
                selectedFileSourceIds.length
              }}）
            </button>
          </header>
          <div class="source-tabs" role="tablist" aria-label="知识来源类型">
            <button
              v-for="item in sourceTabs"
              :key="item.type"
              type="button"
              :class="{ active: sourceTab === item.type }"
              @click="sourceTab = item.type"
            >
              {{ item.label }} <span>{{ sourceCount(item.type) }}</span>
            </button>
          </div>
          <div v-if="!visibleSources.length" class="source-empty">
            当前没有已导入的{{
              sourceTabs.find((item) => item.type === sourceTab)?.label
            }}。
          </div>
          <div v-else class="source-table-wrap">
            <table class="source-table">
              <thead>
                <tr>
                  <th v-if="sourceTab === 'FILE'" class="check-cell">
                    <input
                      type="checkbox"
                      :checked="allVisibleFilesSelected"
                      aria-label="选择全部文件"
                      @change="toggleAllFiles"
                    />
                  </th>
                  <th>名称</th>
                  <th v-if="sourceTab !== 'FILE'">来源地址</th>
                  <th>状态</th>
                  <th>内容</th>
                  <th>最近更新</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="source in visibleSources" :key="source.id">
                  <td v-if="sourceTab === 'FILE'" class="check-cell">
                    <input
                      v-model="selectedFileSourceIds"
                      type="checkbox"
                      :value="source.id"
                      :aria-label="`选择 ${source.display_name}`"
                    />
                  </td>
                  <td>
                    <b>{{ source.display_name }}</b>
                    <small>{{ source.version_count }} 个版本</small>
                  </td>
                  <td v-if="sourceTab !== 'FILE'" class="source-location">
                    <span :title="source.source_locator">{{
                      source.source_locator
                    }}</span>
                  </td>
                  <td>
                    <span class="source-status">{{
                      sourceStatus(source)
                    }}</span>
                  </td>
                  <td>{{ source.chunk_count }} 个分块</td>
                  <td>{{ formatDate(source.last_synced_at) }}</td>
                  <td class="source-actions">
                    <button
                      v-if="sourceTab !== 'FILE'"
                      class="secondary"
                      :disabled="busy"
                      title="从原地址检查并更新"
                      @click="refreshSource(source)"
                    >
                      <RefreshCw :size="14" />更新
                    </button>
                    <button
                      class="danger"
                      :disabled="busy"
                      title="删除来源"
                      @click="deleteSource(source)"
                    >
                      <Trash2 :size="14" />删除
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section class="table-section">
          <h3>候选知识审核</h3>
          <table>
            <thead>
              <tr>
                <th>名称 / 关系</th>
                <th>置信度</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in candidates.entities" :key="e.id">
                <td>
                  {{ e.name }} <small>{{ e.type }}</small>
                </td>
                <td>{{ Math.round(e.confidence * 100) }}%</td>
                <td>
                  <button @click="review('entities', e.id, 'accept')">
                    通过
                  </button>
                  <button
                    class="danger"
                    @click="review('entities', e.id, 'reject')"
                  >
                    拒绝
                  </button>
                </td>
              </tr>
              <tr v-for="r in candidates.relations" :key="r.id">
                <td>{{ r.predicate }}</td>
                <td>{{ Math.round(r.confidence * 100) }}%</td>
                <td>
                  <button @click="review('relations', r.id, 'accept')">
                    通过
                  </button>
                  <button
                    class="danger"
                    @click="review('relations', r.id, 'reject')"
                  >
                    拒绝
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>

      <section v-else-if="tab === 'review'" class="table-section">
        <table>
          <thead>
            <tr>
              <th>知识</th>
              <th>掌握度</th>
              <th>间隔</th>
              <th>到期</th>
              <th>评分</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in reviews" :key="r.id">
              <td>{{ r.entityName }}</td>
              <td>{{ Math.round(r.mastery * 100) }}%</td>
              <td>{{ r.intervalDays }} 天</td>
              <td>{{ new Date(r.dueAt).toLocaleDateString() }}</td>
              <td class="grade-actions">
                <button
                  v-for="gradeValue in [1, 2, 3, 4, 5]"
                  :key="gradeValue"
                  @click="grade(r.entityId, gradeValue)"
                >
                  {{ gradeValue }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-else-if="tab === 'graph'" class="graph-panel">
        <div v-if="!graphData.nodes.length" class="empty-graph">
          <div class="bear-blob tiny">
            <span class="ear left"></span><span class="ear right"></span>
            <span class="eye left"></span><span class="eye right"></span>
            <span class="nose"></span>
          </div>
          <h3>暂无可视化图谱</h3>
          <p>重新导入简历、项目或网页后，候选知识会在这里形成节点与关系。</p>
        </div>
        <svg v-else viewBox="0 0 720 380" role="img" aria-label="知识图谱">
          <line
            v-for="edge in graphData.edges"
            :key="edge.id"
            :x1="graphNodeById[edge.source]?.x"
            :y1="graphNodeById[edge.source]?.y"
            :x2="graphNodeById[edge.target]?.x"
            :y2="graphNodeById[edge.target]?.y"
            class="graph-edge"
          />
          <text
            v-for="edge in graphData.edges"
            :key="`${edge.id}-label`"
            :x="
              ((graphNodeById[edge.source]?.x || 0) +
                (graphNodeById[edge.target]?.x || 0)) /
              2
            "
            :y="
              ((graphNodeById[edge.source]?.y || 0) +
                (graphNodeById[edge.target]?.y || 0)) /
              2
            "
            class="graph-edge-label"
          >
            {{ edge.label }}
          </text>
          <g v-for="node in graphNodes" :key="node.id">
            <circle
              :cx="node.x"
              :cy="node.y"
              r="28"
              :class="['graph-node', node.status.toLowerCase()]"
            />
            <text
              :x="node.x"
              :y="node.y + 45"
              text-anchor="middle"
              class="graph-label"
            >
              {{ node.label.slice(0, 12) }}
            </text>
          </g>
        </svg>
      </section>

      <section v-else class="table-section">
        <table>
          <thead>
            <tr>
              <th>岗位</th>
              <th>评论</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in visitorFeedback" :key="item.id">
              <td>{{ item.position }}</td>
              <td>{{ item.comment }}</td>
              <td>
                {{
                  new Date(item.createdAt || item.created_at).toLocaleString()
                }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </section>
  </div>
</template>
