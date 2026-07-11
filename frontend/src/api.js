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
  if (!response.ok) throw new Error("Unable to start conversation");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop();
    for (const raw of events) {
      const lines = raw.split("\n");
      const type = lines
        .find((x) => x.startsWith("event:"))
        ?.slice(6)
        .trim();
      const data = lines
        .find((x) => x.startsWith("data:"))
        ?.slice(5)
        .trim();
      if (type && data) onEvent(type, JSON.parse(data));
    }
  }
}
