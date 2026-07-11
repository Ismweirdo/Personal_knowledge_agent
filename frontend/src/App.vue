<script setup>
import { ref, computed, onMounted } from "vue";
import {
  BookOpen,
  Brain,
  FileUp,
  GitBranch,
  LogOut,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldCheck,
} from "@lucide/vue";
import { api, stream, token } from "./api";
const user = ref(null),
  mode = ref("login"),
  email = ref(""),
  password = ref(""),
  error = ref(""),
  busy = ref(false);
const agent = ref(null),
  conversation = ref(null),
  question = ref(""),
  messages = ref([]),
  citations = ref([]);
const tab = ref("knowledge"),
  knowledgeBases = ref([]),
  selectedKb = ref(""),
  webUrl = ref(""),
  gitPath = ref(""),
  candidates = ref({ entities: [], relations: [] }),
  reviews = ref([]),
  notice = ref("");
const isAdmin = computed(() => user.value?.role === "ADMIN");
const roleLabels = { ADMIN: "管理员", USER: "用户" };
const taskStatusLabels = {
  PENDING: "等待处理",
  RUNNING: "处理中",
  RETRY_WAIT: "等待重试",
  SUCCEEDED: "已完成",
  FAILED: "失败",
};
async function loadUser() {
  if (!token.get()) return;
  try {
    user.value = await api("/auth/me");
    await afterLogin();
  } catch {
    token.set(null);
  }
}
async function authenticate() {
  busy.value = true;
  error.value = "";
  try {
    const data = await api(`/auth/${mode.value}`, {
      method: "POST",
      body: JSON.stringify({ email: email.value, password: password.value }),
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
  else agent.value = await api("/agent");
}
function logout() {
  token.set(null);
  user.value = null;
  messages.value = [];
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
  notice.value = `已解析 ${result.chunk_count} 个文本块，后台任务已加入队列`;
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
    ? "知识源内容没有变化"
    : `已创建 ${result.chunk_count} 个文本块，后台任务已加入队列`;
  if (result.task_id) trackTask(result.task_id);
}
async function trackTask(taskId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const task = await api(`/admin/tasks/${taskId}`);
    notice.value = `入库任务：${taskStatusLabels[task.status] || task.status} · ${task.progress}%`;
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
  notice.value = "入库任务仍在运行，请稍后查看任务状态。";
}
async function review(type, id, action) {
  await api(`/knowledge-candidates/${type}/${id}:${action}`, {
    method: "POST",
    body: "{}",
  });
  await loadAdmin();
}
async function grade(entityId, grade) {
  await api(`/admin/learning/entities/${entityId}/review`, {
    method: "POST",
    body: JSON.stringify({ grade }),
  });
  await loadAdmin();
}
async function ask() {
  if (!question.value.trim() || busy.value) return;
  busy.value = true;
  const text = question.value;
  question.value = "";
  messages.value.push({ role: "user", content: text });
  const reply = { role: "assistant", content: "" };
  messages.value.push(reply);
  try {
    if (!conversation.value)
      conversation.value = await api("/conversations", {
        method: "POST",
        body: JSON.stringify({
          knowledge_base_id: agent.value.knowledgeBaseId,
          title: text.slice(0, 80),
        }),
      });
    await stream(
      `/conversations/${conversation.value.id}/messages:stream`,
      { content: text },
      (type, data) => {
        if (type === "delta") reply.content += data.text;
        if (type === "citation") citations.value = data;
        if (type === "error")
          reply.content = "暂时无法根据当前知识库回答这个问题。";
      },
    );
  } catch (e) {
    reply.content = e.message;
  } finally {
    busy.value = false;
  }
}
onMounted(loadUser);
</script>
<template>
  <main v-if="!user" class="auth-shell">
    <section class="auth-panel">
      <div class="brand"><Brain :size="28" /><span>Laylight Agent</span></div>
      <h1>{{ mode === "login" ? "登录" : "创建账户" }}</h1>
      <p>与我的个人智能体交流项目、经历和学习内容。</p>
      <form @submit.prevent="authenticate">
        <label>邮箱<input v-model="email" type="email" required /></label
        ><label
          >密码<input v-model="password" type="password" minlength="8" required
        /></label>
        <p v-if="error" class="error">{{ error }}</p>
        <button :disabled="busy">
          {{ busy ? "请稍候" : mode === "login" ? "登录" : "注册" }}
        </button>
      </form>
      <button
        class="text-button"
        @click="mode = mode === 'login' ? 'register' : 'login'"
      >
        {{ mode === "login" ? "创建账户" : "返回登录" }}
      </button>
    </section>
  </main>
  <div v-else class="app-shell">
    <aside>
      <div class="brand"><Brain :size="24" /><span>Laylight Agent</span></div>
      <nav v-if="isAdmin">
        <button
          :class="{ active: tab === 'knowledge' }"
          @click="tab = 'knowledge'"
        >
          <BookOpen />知识管理</button
        ><button :class="{ active: tab === 'review' }" @click="tab = 'review'">
          <RefreshCw />学习复习
        </button>
      </nav>
      <nav v-else>
        <button class="active"><MessageSquare />对话</button>
      </nav>
      <div class="account">
        <ShieldCheck v-if="isAdmin" /><span
          >{{ user.email
          }}<small>{{ roleLabels[user.role] || user.role }}</small></span
        ><button title="退出登录" @click="logout"><LogOut /></button>
      </div>
    </aside>
    <section v-if="!isAdmin" class="chat">
      <header>
        <div>
          <h2>{{ agent?.name || "Laylight Agent" }}</h2>
          <p>{{ agent?.description }}</p>
        </div>
      </header>
      <div class="messages">
        <div v-if="!messages.length" class="empty">
          <Brain />
          <h3>开始对话</h3>
          <p>可以询问我的经历、项目或技术学习内容。</p>
        </div>
        <article v-for="(m, i) in messages" :key="i" :class="m.role">
          <strong>{{ m.role === "user" ? "你" : "Laylight Agent" }}</strong>
          <p>{{ m.content }}</p>
        </article>
        <div v-if="citations.length" class="sources">
          <b>参考来源</b
          ><span v-for="c in citations" :key="c.chunkId"
            >[{{ c.index }}] {{ Math.round(c.score * 100) }}%</span
          >
        </div>
      </div>
      <form class="composer" @submit.prevent="ask">
        <textarea
          v-model="question"
          placeholder="输入你的问题..."
          rows="2"
        ></textarea
        ><button title="发送" :disabled="busy"><Send /></button>
      </form>
    </section>
    <section v-else class="workspace">
      <header>
        <div>
          <h2>
            {{ tab === "knowledge" ? "知识管理" : "学习复习" }}
          </h2>
          <p>
            {{
              tab === "knowledge"
                ? "管理 Laylight Agent 对外使用的个人知识。"
                : "按计划复习已激活的知识。"
            }}
          </p>
        </div>
        <button v-if="tab === 'knowledge'" @click="createKb">新建知识库</button>
      </header>
      <template v-if="tab === 'knowledge'"
        ><div class="toolbar">
          <select v-model="selectedKb" @change="loadAdmin">
            <option v-for="kb in knowledgeBases" :value="kb.id">
              {{ kb.name }}
            </option></select
          ><button
            v-if="knowledgeBases.length"
            class="secondary"
            @click="publish(knowledgeBases.find((k) => k.id === selectedKb))"
          >
            {{
              knowledgeBases.find((k) => k.id === selectedKb)?.is_published
                ? "取消发布"
                : "发布 Agent"
            }}
          </button>
        </div>
        <div class="admin-grid">
          <section>
            <h3><FileUp />导入文件</h3>
            <input type="file" accept=".pdf,.md,.txt" @change="uploadFile" />
          </section>
          <section>
            <h3><BookOpen />同步网页</h3>
            <input
              v-model="webUrl"
              placeholder="https://example.com/notes"
            /><button @click="syncSource('web')">同步</button>
          </section>
          <section>
            <h3><GitBranch />同步 Git 项目</h3>
            <input v-model="gitPath" placeholder="已配置的服务器路径" /><button
              @click="syncSource('git')"
            >
              同步
            </button>
          </section>
        </div>
        <p v-if="notice" class="notice">
          {{ notice }}
        </p>
        <section class="table-section">
          <h3>知识候选项</h3>
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
                    接受</button
                  ><button
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
                    接受</button
                  ><button
                    class="danger"
                    @click="review('relations', r.id, 'reject')"
                  >
                    拒绝
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </section></template
      >
      <section v-else class="table-section">
        <table>
          <thead>
            <tr>
              <th>知识</th>
              <th>掌握度</th>
              <th>复习间隔</th>
              <th>到期日期</th>
              <th>评分</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in reviews" :key="r.id">
              <td>{{ r.entityName }}</td>
              <td>{{ Math.round(r.mastery * 100) }}%</td>
              <td>{{ r.intervalDays }} 天</td>
              <td>{{ new Date(r.dueAt).toLocaleDateString("zh-CN") }}</td>
              <td class="grade-actions">
                <button
                  v-for="gradeValue in [1, 2, 3, 4, 5]"
                  :key="gradeValue"
                  :title="`评分 ${gradeValue}`"
                  @click="grade(r.entityId, gradeValue)"
                >
                  {{ gradeValue }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </section>
  </div>
</template>
