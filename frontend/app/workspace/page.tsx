"use client";

import { useEffect, useState } from "react";
import { Button, Card, Select, Textarea } from "flowbite-react";

import { Monaco } from "@/components/Monaco";
import { Plot } from "@/components/PlotlyChart";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type CellType = "markdown" | "python" | "sql";

type Cell = {
  id: string;
  type: CellType;
  position: number;
  source: string;
  status: "idle" | "running" | "success" | "error";
  stdout: string;
  stderr: string;
  result: any;
  executed_at: string | null;
  runtime_ms: number | null;
};

export default function WorkspacePage() {
  const projectId = useAppStore((s) => s.selectedProjectId);
  const [cells, setCells] = useState<Cell[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<Cell[]>(`/projects/${projectId}/workspace`);
      setCells(data);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  if (!projectId) {
    return (
      <Card>
        <div className="text-sm text-gray-700">Select a project first (Projects page).</div>
      </Card>
    );
  }

  return (
    <div className="max-w-6xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Workspace</h1>
          <div className="text-sm text-gray-600">Notebook-like cells (markdown, python, sql).</div>
        </div>
        <div className="flex gap-2">
          <Button color="gray" onClick={refresh} disabled={loading}>
            Refresh
          </Button>
          <Button
            color="gray"
            onClick={async () => {
              setLoading(true);
              try {
                await apiPost(`/projects/${projectId}/workspace/run_all`, {});
                await refresh();
              } finally {
                setLoading(false);
              }
            }}
          >
            Run all
          </Button>
          <Button
            onClick={async () => {
              await apiPost(`/projects/${projectId}/workspace/cells`, { type: "python", source: "" });
              await refresh();
            }}
          >
            + Python cell
          </Button>
          <Button
            color="gray"
            onClick={async () => {
              await apiPost(`/projects/${projectId}/workspace/cells`, { type: "markdown", source: "" });
              await refresh();
            }}
          >
            + Markdown
          </Button>
          <Button
            color="gray"
            onClick={async () => {
              await apiPost(`/projects/${projectId}/workspace/cells`, { type: "sql", source: "" });
              await refresh();
            }}
          >
            + SQL
          </Button>
        </div>
      </div>

      {error && <Card className="border-red-200 bg-red-50">{error}</Card>}

      <div className="space-y-4">
        {cells.map((c) => (
          <Card key={c.id}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Select
                  value={c.type}
                  onChange={async (e) => {
                    // v1: type change via patching source only; keep type fixed for now.
                    const next = e.target.value as CellType;
                    if (next !== c.type) {
                      setError("Changing cell type is not supported in v1.");
                    }
                  }}
                >
                  <option value="markdown">markdown</option>
                  <option value="python">python</option>
                  <option value="sql">sql</option>
                </Select>
                <div className="text-xs text-gray-500">
                  #{c.position} · {c.status}
                  {c.runtime_ms ? ` · ${c.runtime_ms}ms` : ""}
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  size="xs"
                  color="gray"
                  disabled={loading}
                  onClick={async () => {
                    const idx = cells.findIndex((x) => x.id === c.id);
                    if (idx <= 0) return;
                    const prev = cells[idx - 1];
                    // swap positions
                    await apiPatch(`/projects/${projectId}/workspace/cells/${c.id}`, { position: prev.position });
                    await apiPatch(`/projects/${projectId}/workspace/cells/${prev.id}`, { position: c.position });
                    await refresh();
                  }}
                >
                  ↑
                </Button>
                <Button
                  size="xs"
                  color="gray"
                  disabled={loading}
                  onClick={async () => {
                    const idx = cells.findIndex((x) => x.id === c.id);
                    if (idx < 0 || idx >= cells.length - 1) return;
                    const next = cells[idx + 1];
                    await apiPatch(`/projects/${projectId}/workspace/cells/${c.id}`, { position: next.position });
                    await apiPatch(`/projects/${projectId}/workspace/cells/${next.id}`, { position: c.position });
                    await refresh();
                  }}
                >
                  ↓
                </Button>
                {(c.type === "python" || c.type === "sql") && (
                  <Button
                    size="xs"
                    onClick={async () => {
                      setLoading(true);
                      try {
                        await apiPost(`/projects/${projectId}/workspace/cells/${c.id}/run`, {});
                        await refresh();
                      } catch (e: any) {
                        setError(e?.message || String(e));
                      } finally {
                        setLoading(false);
                      }
                    }}
                  >
                    Run
                  </Button>
                )}
              </div>
            </div>

            <div className="mt-3">
              {c.type === "markdown" ? (
                <Textarea
                  rows={4}
                  value={c.source}
                  onChange={(e) => {
                    const next = e.target.value;
                    setCells((all) => all.map((x) => (x.id === c.id ? { ...x, source: next } : x)));
                  }}
                  onBlur={async () => {
                    await apiPatch(`/projects/${projectId}/workspace/cells/${c.id}`, { source: c.source });
                  }}
                  placeholder="Markdown..."
                />
              ) : (
                <div className="h-56 overflow-hidden rounded border">
                  <Monaco
                    height="100%"
                    defaultLanguage={c.type === "sql" ? "sql" : "python"}
                    value={c.source}
                    onChange={(v) => {
                      const next = v || "";
                      setCells((all) => all.map((x) => (x.id === c.id ? { ...x, source: next } : x)));
                    }}
                    onMount={() => {
                      // no-op
                    }}
                    options={{ minimap: { enabled: false }, fontSize: 13 }}
                  />
                </div>
              )}

              {(c.type === "python" || c.type === "sql") && (
                <div className="mt-2 flex justify-end">
                  <Button
                    size="xs"
                    color="gray"
                    onClick={async () => {
                      await apiPatch(`/projects/${projectId}/workspace/cells/${c.id}`, { source: c.source });
                    }}
                  >
                    Save
                  </Button>
                </div>
              )}
            </div>

            {(c.stdout || c.stderr || c.result) && (
              <div className="mt-4 space-y-2">
                {c.stdout && (
                  <div>
                    <div className="text-xs font-semibold text-gray-500">stdout</div>
                    <pre className="mt-1 whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs">{c.stdout}</pre>
                  </div>
                )}
                {c.stderr && (
                  <div>
                    <div className="text-xs font-semibold text-gray-500">stderr</div>
                    <pre className="mt-1 whitespace-pre-wrap rounded bg-red-50 p-2 text-xs text-red-800">{c.stderr}</pre>
                  </div>
                )}

                {c.result?.type === "table" && (
                  <div>
                    <div className="text-xs font-semibold text-gray-500">table</div>
                    <div className="mt-1 overflow-auto">
                      <table className="min-w-full text-xs">
                        <thead>
                          <tr>
                            {c.result.columns.map((col: string) => (
                              <th key={col} className="border-b px-2 py-1 text-left font-semibold">
                                {col}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {c.result.rows.map((row: any[], i: number) => (
                            <tr key={i} className={i % 2 ? "bg-gray-50" : "bg-white"}>
                              {row.map((v: any, j: number) => (
                                <td key={j} className="border-b px-2 py-1">
                                  {String(v)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {c.result?.type === "plotly" && c.result.figure && (
                  <div>
                    <div className="text-xs font-semibold text-gray-500">plot</div>
                    <div className="mt-2">
                      <Plot
                        data={c.result.figure.data}
                        layout={{ ...c.result.figure.layout, height: 420 }}
                        config={{ displayModeBar: true, responsive: true }}
                        style={{ width: "100%" }}
                      />
                    </div>
                  </div>
                )}

                {c.result?.type === "text" && (
                  <div>
                    <div className="text-xs font-semibold text-gray-500">result</div>
                    <pre className="mt-1 whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs">{c.result.text}</pre>
                  </div>
                )}
              </div>
            )}
          </Card>
        ))}

        {cells.length === 0 && (
          <Card>
            <div className="text-sm text-gray-600">
              No cells yet. Add a Python cell to begin.
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
