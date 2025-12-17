"use client";

import { useEffect, useMemo, useState } from "react";
import { Button, Card, Label, Select, TextInput } from "flowbite-react";

import { Monaco } from "@/components/Monaco";
import { Plot } from "@/components/PlotlyChart";
import { apiPost } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type SQLGenerateOut = { sql: string; explanation: string; safety_notes: string };

type SQLRunOut = { columns: string[]; rows: any[][]; row_count: number };

export default function SqlPage() {
  const projectId = useAppStore((s) => s.selectedProjectId);
  const sqlDraft = useAppStore((s) => s.sqlDraft);
  const setSqlDraft = useAppStore((s) => s.setSqlDraft);

  const [question, setQuestion] = useState("");
  const [sql, setSql] = useState("");
  const [result, setResult] = useState<SQLRunOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [xCol, setXCol] = useState<string>("");
  const [yCol, setYCol] = useState<string>("");

  useEffect(() => {
    if (sqlDraft && !sql) setSql(sqlDraft);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sqlDraft]);

  const columns = result?.columns || [];
  const plotData = useMemo(() => {
    if (!result || !xCol || !yCol) return null;
    const xi = columns.indexOf(xCol);
    const yi = columns.indexOf(yCol);
    if (xi < 0 || yi < 0) return null;
    return {
      x: result.rows.map((r) => r[xi]),
      y: result.rows.map((r) => r[yi]),
    };
  }, [result, xCol, yCol, columns]);

  if (!projectId) {
    return (
      <Card>
        <div className="text-sm text-gray-700">Select a project first (Projects page).</div>
      </Card>
    );
  }

  return (
    <div className="max-w-6xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">SQL</h1>
        <div className="text-sm text-gray-600">Generate SQL from natural language and run queries.</div>
      </div>

      {error && <Card className="border-red-200 bg-red-50">{error}</Card>}

      <Card>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="md:col-span-2">
            <Label>Natural language → SQL</Label>
            <div className="mt-1 flex gap-2">
              <TextInput
                className="flex-1"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder='e.g. "show me top 10 rows of table my_table"'
              />
              <Button
                color="gray"
                disabled={loading || !question.trim()}
                onClick={async () => {
                  setLoading(true);
                  setError(null);
                  try {
                    const out = await apiPost<SQLGenerateOut>(
                      `/projects/${projectId}/sql/generate`,
                      { question }
                    );
                    setSql(out.sql);
                    setSqlDraft(out.sql);
                  } catch (e: any) {
                    setError(e?.message || String(e));
                  } finally {
                    setLoading(false);
                  }
                }}
              >
                Generate
              </Button>
            </div>
          </div>

          <div>
            <Label>Actions</Label>
            <div className="mt-1 flex gap-2">
              <Button
                disabled={loading || !sql.trim()}
                onClick={async () => {
                  setLoading(true);
                  setError(null);
                  try {
                    const out = await apiPost<SQLRunOut>(
                      `/projects/${projectId}/sql/run`,
                      { sql }
                    );
                    setResult(out);
                    setXCol(out.columns[0] || "");
                    setYCol(out.columns[1] || "");
                  } catch (e: any) {
                    setError(e?.message || String(e));
                  } finally {
                    setLoading(false);
                  }
                }}
              >
                Run
              </Button>
              <Button color="gray" onClick={() => { setSql(""); setSqlDraft(""); setResult(null); }}>
                Clear
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-4">
          <Label>SQL editor</Label>
          <div className="mt-2 h-64 overflow-hidden rounded border">
            <Monaco
              height="100%"
              defaultLanguage="sql"
              value={sql}
              onChange={(v) => {
                const next = v || "";
                setSql(next);
                setSqlDraft(next);
              }}
              options={{ minimap: { enabled: false }, fontSize: 13 }}
            />
          </div>
        </div>
      </Card>

      {result && (
        <Card>
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold">Results</div>
            <div className="text-xs text-gray-500">Rows: {result.row_count} (preview)</div>
          </div>

          <div className="mt-3 overflow-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr>
                  {result.columns.map((c) => (
                    <th key={c} className="border-b px-2 py-1 text-left font-semibold">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r, i) => (
                  <tr key={i} className={i % 2 ? "bg-gray-50" : "bg-white"}>
                    {r.map((v, j) => (
                      <td key={j} className="border-b px-2 py-1">
                        {String(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-6">
            <div className="text-sm font-semibold">Quick plot</div>
            <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-3">
              <div>
                <Label>X</Label>
                <Select value={xCol} onChange={(e) => setXCol(e.target.value)}>
                  {columns.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label>Y</Label>
                <Select value={yCol} onChange={(e) => setYCol(e.target.value)}>
                  {columns.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex items-end">
                <Button color="gray" onClick={() => setResult(result)}>
                  Update
                </Button>
              </div>
            </div>

            {plotData && (
              <div className="mt-4">
                <Plot
                  data={[{ type: "scatter", mode: "markers", x: plotData.x, y: plotData.y }]}
                  layout={{ height: 420, margin: { l: 40, r: 20, t: 20, b: 40 } }}
                  config={{ displayModeBar: true, responsive: true }}
                  style={{ width: "100%" }}
                />
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
