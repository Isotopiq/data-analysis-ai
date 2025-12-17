"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, Textarea } from "flowbite-react";

import { API_BASE_URL, apiGet, apiPost } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta: any;
  created_at: string;
};

export default function ChatPage() {
  const router = useRouter();
  const projectId = useAppStore((s) => s.selectedProjectId);
  const setSqlDraft = useAppStore((s) => s.setSqlDraft);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadHistory() {
    if (!projectId) return;
    const data = await apiGet<ChatMessage[]>(`/projects/${projectId}/chat/history`);
    setMessages(data);
  }

  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const canSend = useMemo(() => !!projectId && input.trim().length > 0 && !loading, [projectId, input, loading]);

  async function send() {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    const text = input;
    setInput("");
    try {
      // Optimistic add user message
      setMessages((m) => [
        ...m,
        { id: `tmp-${Date.now()}`, role: "user", content: text, meta: {}, created_at: new Date().toISOString() },
      ]);
      // Streaming (SSE)
      const assistantId = `tmp-a-${Date.now()}`;
      setMessages((m) => [
        ...m,
        { id: assistantId, role: "assistant", content: "", meta: {}, created_at: new Date().toISOString() },
      ]);

      const res = await fetch(`${API_BASE_URL}/projects/${projectId}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok || !res.body) throw new Error(await res.text());

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let content = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          const lines = part.split("\n");
          let event: string | null = null;
          let dataLines: string[] = [];
          for (const line of lines) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
          }
          const data = dataLines.join("\n");
          if (event === "delta") {
            content += data;
            setMessages((m) =>
              m.map((x) => (x.id === assistantId ? { ...x, content } : x))
            );
          }
        }
      }

      // Refresh history to fetch persisted meta/actions.
      await loadHistory();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  if (!projectId) {
    return (
      <Card>
        <div className="text-sm text-gray-700">
          Select a project first (go to <span className="font-medium">Projects</span>).
        </div>
      </Card>
    );
  }

  return (
    <div className="max-w-5xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Chat</h1>
        <div className="text-sm text-gray-600">Ask questions and generate SQL / workspace artifacts.</div>
      </div>

      {error && <Card className="border-red-200 bg-red-50">{error}</Card>}

      <div className="space-y-3">
        {messages.map((m) => (
          <Card key={m.id} className={m.role === "assistant" ? "bg-white" : "bg-gray-50"}>
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold uppercase text-gray-500">{m.role}</div>
              <div className="text-xs text-gray-400">{new Date(m.created_at).toLocaleString()}</div>
            </div>
            <pre className="mt-2 whitespace-pre-wrap text-sm text-gray-900">{m.content}</pre>

            {m.role === "assistant" && m.meta?.actions?.length ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {m.meta.actions.map((a: any, idx: number) => {
                  if (a.type === "insert_sql") {
                    return (
                      <Button
                        key={idx}
                        size="xs"
                        onClick={() => {
                          setSqlDraft(a.sql || "");
                          router.push("/sql");
                        }}
                      >
                        Insert SQL into editor
                      </Button>
                    );
                  }

                  if (a.type === "create_sql_cell") {
                    return (
                      <Button
                        key={idx}
                        size="xs"
                        color="gray"
                        onClick={async () => {
                          await apiPost(`/projects/${projectId}/workspace/cells`, { type: "sql", source: a.sql || "" });
                          router.push("/workspace");
                        }}
                      >
                        Create SQL cell in workspace
                      </Button>
                    );
                  }

                  return null;
                })}
              </div>
            ) : null}

            {m.role === "assistant" && m.meta?.citations?.length ? (
              <div className="mt-3 text-xs text-gray-500">
                <div className="font-semibold">Context used</div>
                <ul className="list-disc pl-5">
                  {m.meta.citations.map((c: any, idx: number) => (
                    <li key={idx}>
                      {c.type}: {String(c.summary || "").slice(0, 200)}
                      {String(c.summary || "").length > 200 ? "…" : ""}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Card>
        ))}
      </div>

      <Card>
        <div className="space-y-2">
          <Textarea
            rows={3}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask something like: show me top 10 rows of table my_table"
          />
          <div className="flex justify-end">
            <Button onClick={send} disabled={!canSend}>
              {loading ? "Sending…" : "Send"}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
