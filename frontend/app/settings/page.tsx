"use client";

import { useEffect, useState } from "react";
import { Button, Card, Label, Select, TextInput, ToggleSwitch } from "flowbite-react";

import { apiGet, apiPatch } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type Project = {
  id: string;
  name: string;
  llm_provider: "ollama" | "api";
  llm_model: string;
  llm_temperature: number;
  api_base_url: string | null;
  allow_writes: boolean;
  target_db_configured?: boolean;
};

export default function SettingsPage() {
  const projectId = useAppStore((s) => s.selectedProjectId);
  const setSelectedProject = useAppStore((s) => s.setSelectedProject);

  const [p, setP] = useState<Project | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [targetDbUrl, setTargetDbUrl] = useState("");
  const [dbStatus, setDbStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      if (!projectId) return;
      const proj = await apiGet<Project>(`/projects/${projectId}`);
      setP(proj);
      setSelectedProject(proj);
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  if (!projectId) {
    return (
      <Card>
        <div className="text-sm text-gray-700">Select a project first (Projects page).</div>
      </Card>
    );
  }

  if (!p) {
    return <Card>Loading…</Card>;
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <div className="text-sm text-gray-600">Per-project LLM settings and SQL safety toggles.</div>
      </div>

      {error && <Card className="border-red-200 bg-red-50">{error}</Card>}

      <Card>
        <div className="space-y-4">
          <div className="rounded border p-3">
            <div className="text-sm font-semibold">Postgres (target DB)</div>
            <div className="mt-1 text-xs text-gray-600">
              Connection string is stored encrypted; it is not displayed back.
            </div>
            <div className="mt-3">
              <Label>Connection string</Label>
              <TextInput
                className="mt-1"
                value={targetDbUrl}
                onChange={(e) => setTargetDbUrl(e.target.value)}
                placeholder="postgresql+asyncpg://user:pass@host:5432/dbname"
              />
              <div className="mt-1 text-xs text-gray-500">
                Current status:{" "}
                <span className="font-medium">
                  {p.target_db_configured ? "Configured" : "Not configured (using default env DB)"}
                </span>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Button
                  size="xs"
                  color="gray"
                  onClick={async () => {
                    try {
                      const out = await apiGet<any>(`/projects/${projectId}/context`);
                      setDbStatus(out?.schema_summary ? "Connected (schema loaded)" : "No schema returned");
                    } catch (e: any) {
                      setDbStatus(e?.message || String(e));
                    }
                  }}
                >
                  Check connection
                </Button>
                {dbStatus && <div className="text-xs text-gray-600">{dbStatus}</div>}
              </div>
            </div>
          </div>

          <div>
            <Label>LLM Provider</Label>
            <Select
              className="mt-1"
              value={p.llm_provider}
              onChange={(e) => setP({ ...p, llm_provider: e.target.value as any })}
            >
              <option value="ollama">Local (Ollama)</option>
              <option value="api">API (OpenAI-compatible)</option>
            </Select>
          </div>

          <div>
            <Label>Model name</Label>
            <TextInput
              className="mt-1"
              value={p.llm_model}
              onChange={(e) => setP({ ...p, llm_model: e.target.value })}
              placeholder="llama3"
            />
          </div>

          {p.llm_provider === "api" && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <Label>API base URL</Label>
                <TextInput
                  className="mt-1"
                  value={p.api_base_url || ""}
                  onChange={(e) => setP({ ...p, api_base_url: e.target.value })}
                  placeholder="https://api.openai.com"
                />
              </div>
              <div>
                <Label>API key</Label>
                <TextInput
                  className="mt-1"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="(stored encrypted)"
                />
              </div>
            </div>
          )}

          <div className="flex items-center justify-between rounded border p-3">
            <div>
              <div className="text-sm font-semibold">Allow SQL writes</div>
              <div className="text-xs text-gray-600">Default is read-only (SELECT/WITH).</div>
            </div>
            <ToggleSwitch
              checked={p.allow_writes}
              label={p.allow_writes ? "On" : "Off"}
              onChange={(v) => setP({ ...p, allow_writes: v })}
            />
          </div>

          <div className="flex justify-end">
            <Button
              disabled={saving}
              onClick={async () => {
                setSaving(true);
                setError(null);
                try {
                  const updated = await apiPatch<Project>(`/projects/${projectId}`, {
                    llm_provider: p.llm_provider,
                    llm_model: p.llm_model,
                    api_base_url: p.api_base_url,
                    api_key: apiKey || undefined,
                    target_database_url: targetDbUrl || undefined,
                    allow_writes: p.allow_writes,
                  });
                  setP(updated);
                  setApiKey("");
                  setTargetDbUrl("");
                  setSelectedProject(updated);
                } catch (e: any) {
                  setError(e?.message || String(e));
                } finally {
                  setSaving(false);
                }
              }}
            >
              Save settings
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
