<script setup>
import { computed, onMounted, ref } from "vue";
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
const citations = ref([]);
const feedbackPosition = ref("");
const feedbackComment = ref("");
const feedbackNotice = ref("");

const tab = ref("knowledge");
const knowledgeBases = ref([]);
const selectedKb = ref("");
const webUrl = ref("");
const gitPath = ref("");
const candidates = ref({ entities: [], relations: [] });
const reviews = ref([]);
const visitorFeedback = ref([]);
const notice = ref("");

const isAdmin = computed(() => user.value?.role === "ADMIN");
const activeKb = computed(() => knowledgeBases.value.find((item) => item.id === selectedKb.value));

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
  const reply = { role: "assistant", content: "" };
  messages.value.push(reply);
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
        if (type === "delta") reply.content += data.text;
        if (type === "citation") citations.value = data;
        if (type === "error") reply.content = "当前知识库证据不足，暂时无法回答。";
      },
    );
  } catch (e) {
    reply.content = e.message;
  } finally {
    busy.value = false;
  }
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
}

async function loadAdmin() {
  knowledgeBases.value = await api("/knowledge-bases");
  selectedKb.value ||= knowledgeBases.value[0]?.id || "";
  if (selectedKb.value) {
    candidates.value = await api(
      `/knowledge-bases/${selectedKb.value}/knowledge-candidates`,
    );
  }
  reviews.value = await api("/admin/learning/review-tasks?include_future=true");
  visitorFeedback.value = await api("/conversations/feedback");
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

async function uploadFile(e) {
  const file = e.target.files[0];
  if (!file || !selectedKb.value) return;
  const body = new FormData();
  body.append("file", file);
  const result = await api(`/knowledge-bases/${selectedKb.value}/documents`, {
    method: "POST",
    body,
  });
  notice.value = `已解析 ${result.chunk_count} 个分块，后台任务已入队`;
  if (result.task_id) trackTask(result.task_id);
  e.target.value = "";
}

async function syncSource(type) {
  const payload =
    type === "web" ? { url: webUrl.value } : { repository_path: gitPath.value };
  const result = await api(
    `/knowledge-bases/${selectedKb.value}/sources:${type}`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  notice.value = result.unchanged
    ? "知识源未变化"
    : `已创建 ${result.chunk_count} 个分块，后台任务已入队`;
  if (result.task_id) trackTask(result.task_id);
}

async function trackTask(taskId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const task = await api(`/admin/tasks/${taskId}`);
    notice.value = `入库任务 ${task.status} · ${task.progress}%`;
    if (task.status === "SUCCEEDED") {
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
    <button class="admin-entry" @click="loginView = loginView === 'admin' ? 'visitor' : 'admin'">
      <ShieldCheck :size="16" />
      {{ loginView === "admin" ? "访客进入" : "管理员登录" }}
    </button>
    <section class="auth-panel">
      <div class="brand"><Brain :size="28" /><span>Laylight Agent</span></div>
      <template v-if="loginView === 'visitor'">
        <h1>输入密钥进入对话</h1>
        <p>与 Laylight 的个人知识库 Agent 对话。</p>
        <form @submit.prevent="visitorAccess">
          <label>访问密钥<input v-model="accessKey" type="password" required /></label>
          <p v-if="error" class="error">{{ error }}</p>
          <button :disabled="busy">{{ busy ? "进入中" : "进入网站" }}</button>
        </form>
      </template>
      <template v-else>
        <h1>管理员登录</h1>
        <p>管理知识库、学习任务和访客反馈。</p>
        <form @submit.prevent="adminLogin">
          <label>账号<input v-model="adminUsername" autocomplete="username" required /></label>
          <label>密码<input v-model="adminPassword" type="password" required /></label>
          <p v-if="error" class="error">{{ error }}</p>
          <button :disabled="busy">{{ busy ? "登录中" : "登录管理端" }}</button>
        </form>
      </template>
    </section>
  </main>

  <div v-else class="app-shell">
    <aside>
      <div class="brand"><Brain :size="24" /><span>Laylight Agent</span></div>
      <nav v-if="isAdmin">
        <button :class="{ active: tab === 'knowledge' }" @click="tab = 'knowledge'">
          <BookOpen />知识库
        </button>
        <button :class="{ active: tab === 'review' }" @click="tab = 'review'">
          <RefreshCw />复习
        </button>
        <button :class="{ active: tab === 'feedback' }" @click="tab = 'feedback'">
          <MessageSquare />评论
        </button>
      </nav>
      <nav v-else>
        <button class="active"><MessageSquare />对话</button>
      </nav>
      <div class="account">
        <ShieldCheck v-if="isAdmin" />
        <span>{{ isAdmin ? "管理员" : "访客" }}<small>{{ user.email }}</small></span>
        <button title="退出" @click="logout"><LogOut /></button>
      </div>
    </aside>

    <section v-if="!isAdmin" class="chat-layout">
      <div class="conversation-sidebar">
        <button class="new-chat" @click="newConversation"><Plus :size="16" />新建对话</button>
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
      </div>
      <section class="chat">
        <header>
          <div>
            <h2>{{ agent?.name || "个人知识库问答" }}</h2>
            <p>{{ agent?.description || "围绕我的经历、项目和学习内容进行回答。" }}</p>
          </div>
        </header>
        <div class="messages">
          <div v-if="!messages.length" class="empty">
            <Brain />
            <h3>开始一段新对话</h3>
            <p>可以询问我的项目经历、技术学习、岗位匹配和后续成长方向。</p>
          </div>
          <article v-for="(m, i) in messages" :key="i" :class="m.role">
            <strong>{{ m.role === "user" ? "你" : "Laylight Agent" }}</strong>
            <p>{{ m.content }}</p>
          </article>
          <div v-if="citations.length" class="sources">
            <b>引用证据</b>
            <span v-for="c in citations" :key="c.chunkId">
              [{{ c.index }}] {{ Math.round(c.score * 100) }}%
            </span>
          </div>
        </div>
        <form class="composer" @submit.prevent="ask">
          <textarea v-model="question" placeholder="请输入问题..." rows="2"></textarea>
          <button title="发送" :disabled="busy"><Send /></button>
        </form>
        <section class="feedback-panel">
          <form @submit.prevent="submitFeedback">
            <label>岗位<input v-model="feedbackPosition" placeholder="例如：后端开发工程师" /></label>
            <label>评论<textarea v-model="feedbackComment" rows="3" placeholder="写下你的建议" /></label>
            <button :disabled="!feedbackPosition || !feedbackComment">提交评论</button>
          </form>
          <aside>
            <p>欢迎根据岗位对我提出学习与补充建议，谢谢:D</p>
            <small v-if="feedbackNotice">{{ feedbackNotice }}</small>
          </aside>
        </section>
      </section>
    </section>

    <section v-else class="workspace">
      <header>
        <div>
          <h2>{{ tab === "knowledge" ? "知识库管理" : tab === "review" ? "学习复习" : "访客评论" }}</h2>
          <p>
            {{
              tab === "knowledge"
                ? "维护公开 Agent 背后的个人知识资产。"
                : tab === "review"
                  ? "按复习计划巩固已抽取的知识实体。"
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
          <button v-if="knowledgeBases.length" class="secondary" @click="publish(activeKb)">
            {{ activeKb?.is_published ? "取消发布" : "发布 Agent" }}
          </button>
        </div>
        <div class="admin-grid">
          <section>
            <h3><FileUp />导入文件</h3>
            <input type="file" accept=".pdf,.md,.txt" @change="uploadFile" />
          </section>
          <section>
            <h3><BookOpen />同步网页</h3>
            <input v-model="webUrl" placeholder="https://example.com/notes" />
            <button @click="syncSource('web')">同步</button>
          </section>
          <section>
            <h3><GitBranch />同步 Git 项目</h3>
            <input v-model="gitPath" placeholder="服务器允许导入的项目路径" />
            <button @click="syncSource('git')">同步</button>
          </section>
        </div>
        <p v-if="notice" class="notice">{{ notice }}</p>
        <section class="table-section">
          <h3>候选知识审核</h3>
          <table>
            <thead>
              <tr><th>名称 / 关系</th><th>置信度</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="e in candidates.entities" :key="e.id">
                <td>{{ e.name }} <small>{{ e.type }}</small></td>
                <td>{{ Math.round(e.confidence * 100) }}%</td>
                <td>
                  <button @click="review('entities', e.id, 'accept')">通过</button>
                  <button class="danger" @click="review('entities', e.id, 'reject')">拒绝</button>
                </td>
              </tr>
              <tr v-for="r in candidates.relations" :key="r.id">
                <td>{{ r.predicate }}</td>
                <td>{{ Math.round(r.confidence * 100) }}%</td>
                <td>
                  <button @click="review('relations', r.id, 'accept')">通过</button>
                  <button class="danger" @click="review('relations', r.id, 'reject')">拒绝</button>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>

      <section v-else-if="tab === 'review'" class="table-section">
        <table>
          <thead>
            <tr><th>知识</th><th>掌握度</th><th>间隔</th><th>到期</th><th>评分</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in reviews" :key="r.id">
              <td>{{ r.entityName }}</td>
              <td>{{ Math.round(r.mastery * 100) }}%</td>
              <td>{{ r.intervalDays }} 天</td>
              <td>{{ new Date(r.dueAt).toLocaleDateString() }}</td>
              <td class="grade-actions">
                <button v-for="gradeValue in [1, 2, 3, 4, 5]" :key="gradeValue" @click="grade(r.entityId, gradeValue)">
                  {{ gradeValue }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-else class="table-section">
        <table>
          <thead>
            <tr><th>岗位</th><th>评论</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in visitorFeedback" :key="item.id">
              <td>{{ item.position }}</td>
              <td>{{ item.comment }}</td>
              <td>{{ new Date(item.createdAt || item.created_at).toLocaleString() }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </section>
  </div>
</template>
