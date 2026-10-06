export interface NoteMeta {
  path: string;
  name: string;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `${res.status}`);
  }
  return res.json();
}

export const api = {
  workspace: () => req<{ path: string | null }>("/api/workspace"),
  openWorkspace: (path: string) =>
    req<{ path: string }>("/api/workspace/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  createWorkspace: (path: string) =>
    req<{ path: string }>("/api/workspace/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  listNotes: () => req<{ notes: NoteMeta[] }>("/api/notes"),
  noteNames: () => req<{ notes: NoteMeta[] }>("/api/notes/names"),
  readNote: (path: string) =>
    req<{ path: string; content: string }>(`/api/notes/content?path=${encodeURIComponent(path)}`),
  writeNote: (path: string, content: string) =>
    req<{ path: string }>("/api/notes/content", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content }),
    }),
  createNote: (path: string) =>
    req<NoteMeta>("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  search: (q: string) =>
    req<{ results: { path: string; name: string; in_title: boolean; snippet: string }[] }>(
      `/api/search?q=${encodeURIComponent(q)}`
    ),
  backlinks: (path: string) =>
    req<{ backlinks: NoteMeta[] }>(`/api/notes/backlinks?path=${encodeURIComponent(path)}`),
  resolve: (target: string) =>
    req<{ status: "ok" | "missing" | "ambiguous"; matches: string[] }>(
      `/api/links/resolve?target=${encodeURIComponent(target)}`
    ),
};
