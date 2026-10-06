export interface NoteMeta {
  path: string;
  name: string;
}

export interface SearchHit {
  kind: string;
  path: string;
  content: string;
  pages: string;
  score: number;
  lex_score: number;
  vector_score: number;
  via: string[];
  rank: number;
  status: string;
}

export interface SourceStatus {
  path: string;
  indexed_path: string;
  status: string;
  error: string | null;
}

export interface ChatStatus {
  configured: boolean;
  model: string | null;
  knowledge_model: string | null;
  base_host: string | null;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at?: string;
}

export interface ContextItem {
  label: string;
  kind: "note" | "source";
  path: string;
  pages: string;
  snippet: string;
  status: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  status: string;
  citations: string[] | null;
  context: ContextItem[] | null;
  created_at: string;
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
  searchNotes: (q: string) =>
    req<{ results: SearchHit[] }>(`/api/search/notes?q=${encodeURIComponent(q)}`),
  searchSources: (q: string) =>
    req<{ results: SearchHit[] }>(`/api/search/sources?q=${encodeURIComponent(q)}`),
  listSources: () => req<{ sources: SourceStatus[]; db_available: boolean }>("/api/sources"),
  rescanSources: () => req<any>("/api/sources/rescan", { method: "POST" }),
  reindexSources: (full: boolean) =>
    req<any>("/api/sources/reindex", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full }),
    }),
  chatStatus: () => req<ChatStatus>("/api/chat/status"),
  listConversations: () => req<{ conversations: Conversation[] }>("/api/conversations"),
  createConversation: (title: string) =>
    req<Conversation>("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  getConversation: (id: number) =>
    req<{ id: number; title: string; messages: ChatMessage[] }>(`/api/conversations/${id}`),
};
