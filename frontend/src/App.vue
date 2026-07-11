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
} from "lucide-vue-next";
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
  notice = ref(""),
  lastSource = ref("");
const isAdmin = computed(() => user.value?.role === "ADMIN");
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
  const name = prompt("Knowledge base name");
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
  lastSource.value = result.source_id;
  notice.value = `Parsed ${result.chunk_count} chunks`;
  e.target.value = "";
}
async function syncSource(type) {
  const payload =
    type === "web" ? { url: webUrl.value } : { repository_path: gitPath.value };
  const result = await api(
    `/knowledge-bases/${selectedKb.value}/sources:${type}`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  lastSource.value = result.source_id;
  notice.value = result.unchanged
    ? "Source unchanged"
    : `Created ${result.chunk_count} chunks`;
}
async function indexSource() {
  const result = await api(`/sources/${lastSource.value}/index`, {
    method: "POST",
  });
  notice.value = `Indexed ${result.indexedChunks} chunks`;
  lastSource.value = "";
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
          reply.content = "Unable to answer from the current knowledge.";
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
      <div class="brand">
        <Brain :size="28" /><span>Lei Mingkang Agent</span>
      </div>
      <h1>{{ mode === "login" ? "Sign in" : "Create account" }}</h1>
      <p>Ask about my projects, experience and learning.</p>
      <form @submit.prevent="authenticate">
        <label>Email<input v-model="email" type="email" required /></label
        ><label
          >Password<input
            v-model="password"
            type="password"
            minlength="8"
            required
        /></label>
        <p v-if="error" class="error">{{ error }}</p>
        <button :disabled="busy">
          {{ busy ? "Please wait" : mode === "login" ? "Sign in" : "Register" }}
        </button>
      </form>
      <button
        class="text-button"
        @click="mode = mode === 'login' ? 'register' : 'login'"
      >
        {{ mode === "login" ? "Create an account" : "Back to sign in" }}
      </button>
    </section>
  </main>
  <div v-else class="app-shell">
    <aside>
      <div class="brand"><Brain :size="24" /><span>Personal Agent</span></div>
      <nav v-if="isAdmin">
        <button
          :class="{ active: tab === 'knowledge' }"
          @click="tab = 'knowledge'"
        >
          <BookOpen />Knowledge</button
        ><button :class="{ active: tab === 'review' }" @click="tab = 'review'">
          <RefreshCw />Review
        </button>
      </nav>
      <nav v-else>
        <button class="active"><MessageSquare />Conversation</button>
      </nav>
      <div class="account">
        <ShieldCheck v-if="isAdmin" /><span
          >{{ user.email }}<small>{{ user.role }}</small></span
        ><button title="Sign out" @click="logout"><LogOut /></button>
      </div>
    </aside>
    <section v-if="!isAdmin" class="chat">
      <header>
        <div>
          <h2>{{ agent?.name || "Personal Agent" }}</h2>
          <p>{{ agent?.description }}</p>
        </div>
      </header>
      <div class="messages">
        <div v-if="!messages.length" class="empty">
          <Brain />
          <h3>Start a conversation</h3>
          <p>Ask about my background, projects or technical learning.</p>
        </div>
        <article v-for="(m, i) in messages" :key="i" :class="m.role">
          <strong>{{ m.role === "user" ? "You" : "Agent" }}</strong>
          <p>{{ m.content }}</p>
        </article>
        <div v-if="citations.length" class="sources">
          <b>Sources</b
          ><span v-for="c in citations" :key="c.chunkId"
            >[{{ c.index }}] {{ Math.round(c.score * 100) }}%</span
          >
        </div>
      </div>
      <form class="composer" @submit.prevent="ask">
        <textarea
          v-model="question"
          placeholder="Ask a question..."
          rows="2"
        ></textarea
        ><button title="Send" :disabled="busy"><Send /></button>
      </form>
    </section>
    <section v-else class="workspace">
      <header>
        <div>
          <h2>
            {{
              tab === "knowledge" ? "Knowledge management" : "Learning review"
            }}
          </h2>
          <p>
            {{
              tab === "knowledge"
                ? "Manage the knowledge behind your public Agent."
                : "Review active knowledge on schedule."
            }}
          </p>
        </div>
        <button v-if="tab === 'knowledge'" @click="createKb">
          New knowledge base
        </button>
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
                ? "Unpublish"
                : "Publish Agent"
            }}
          </button>
        </div>
        <div class="admin-grid">
          <section>
            <h3><FileUp />Import file</h3>
            <input type="file" accept=".pdf,.md,.txt" @change="uploadFile" />
          </section>
          <section>
            <h3><BookOpen />Sync webpage</h3>
            <input
              v-model="webUrl"
              placeholder="https://example.com/notes"
            /><button @click="syncSource('web')">Sync</button>
          </section>
          <section>
            <h3><GitBranch />Sync Git project</h3>
            <input
              v-model="gitPath"
              placeholder="Configured server path"
            /><button @click="syncSource('git')">Sync</button>
          </section>
        </div>
        <p v-if="notice" class="notice">
          {{ notice }}
          <button v-if="lastSource" @click="indexSource">Build index</button>
        </p>
        <section class="table-section">
          <h3>Knowledge candidates</h3>
          <table>
            <thead>
              <tr>
                <th>Name / relation</th>
                <th>Confidence</th>
                <th>Action</th>
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
                    Accept</button
                  ><button
                    class="danger"
                    @click="review('entities', e.id, 'reject')"
                  >
                    Reject
                  </button>
                </td>
              </tr>
              <tr v-for="r in candidates.relations" :key="r.id">
                <td>{{ r.predicate }}</td>
                <td>{{ Math.round(r.confidence * 100) }}%</td>
                <td>
                  <button @click="review('relations', r.id, 'accept')">
                    Accept</button
                  ><button
                    class="danger"
                    @click="review('relations', r.id, 'reject')"
                  >
                    Reject
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
              <th>Knowledge</th>
              <th>Mastery</th>
              <th>Interval</th>
              <th>Due</th>
              <th>Grade</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in reviews" :key="r.id">
              <td>{{ r.entityName }}</td>
              <td>{{ Math.round(r.mastery * 100) }}%</td>
              <td>{{ r.intervalDays }} days</td>
              <td>{{ new Date(r.dueAt).toLocaleDateString() }}</td>
              <td class="grade-actions">
                <button
                  v-for="gradeValue in [1, 2, 3, 4, 5]"
                  :key="gradeValue"
                  :title="`Grade ${gradeValue}`"
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
