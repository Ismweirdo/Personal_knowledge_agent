const base = "/api/v1";
export const token = {
  get: () => localStorage.getItem("token"),
  set: (v) =>
    v ? localStorage.setItem("token", v) : localStorage.removeItem("token"),
};
export async function api(path, options = {}) {
  const headers = {
    ...(options.body instanceof FormData
      ? {}
      : { "Content-Type": "application/json" }),
    ...options.headers,
  };
  if (token.get()) headers.Authorization = `Bearer ${token.get()}`;
  const response = await fetch(base + path, { ...options, headers });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}
export async function stream(path, body, onEvent) {
  const response = await fetch(base + path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token.get()}`,
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || "无法开始生成回答");
  }
  if (!response.body) throw new Error("当前浏览器不支持流式回答");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const dispatch = (raw) => {
    const lines = raw.split(/\r?\n/);
    const type = lines
      .find((line) => line.startsWith("event:"))
      ?.slice(6)
      .trim();
    const data = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (type && data) onEvent(type, JSON.parse(data));
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop();
    for (const raw of events) dispatch(raw);
  }
  if (buffer.trim()) dispatch(buffer);
}
