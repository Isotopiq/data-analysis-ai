"use client";

import useSWR from "swr";
import { Card } from "flowbite-react";

import { apiGet } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type FileOut = {
  id: string;
  name: string;
  size_bytes: number;
  mime_type: string | null;
  created_at: string;
};

type CellOut = {
  id: string;
  type: "markdown" | "python" | "sql";
  position: number;
  status: "idle" | "running" | "success" | "error";
  executed_at: string | null;
};

type ContextOut = {
  schema_summary: string;
  files: FileOut[];
  recent_cells: CellOut[];
};

export function ProjectContextDrawer() {
  const projectId = useAppStore((s) => s.selectedProjectId);

  const { data, error, isLoading } = useSWR<ContextOut>(
    projectId ? `/projects/${projectId}/context` : null,
    (path) => apiGet<ContextOut>(path),
    { refreshInterval: 5000 }
  );

  if (!projectId) {
    return (
      <div className="text-xs text-gray-600">Select a project to see context.</div>
    );
  }

  if (isLoading) return <div className="text-xs text-gray-600">Loading context…</div>;
  if (error) return <div className="text-xs text-red-600">Failed to load context.</div>;
  if (!data) return null;

  return (
    <div className="space-y-3">
      <Card>
        <div className="text-xs font-semibold text-gray-700">Postgres schema</div>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-[11px] text-gray-600">
          {data.schema_summary || "(empty)"}
        </pre>
      </Card>

      <Card>
        <div className="text-xs font-semibold text-gray-700">Files</div>
        <div className="mt-2 space-y-1">
          {data.files.length === 0 ? (
            <div className="text-xs text-gray-500">No files uploaded.</div>
          ) : (
            data.files.slice(0, 10).map((f) => (
              <div key={f.id} className="text-[11px] text-gray-600">
                {f.name} <span className="text-gray-400">({(f.size_bytes / 1024).toFixed(1)} KB)</span>
              </div>
            ))
          )}
        </div>
      </Card>

      <Card>
        <div className="text-xs font-semibold text-gray-700">Recent cells</div>
        <div className="mt-2 space-y-1">
          {data.recent_cells.length === 0 ? (
            <div className="text-xs text-gray-500">No cells yet.</div>
          ) : (
            data.recent_cells.map((c) => (
              <div key={c.id} className="text-[11px] text-gray-600">
                {c.type} #{c.position} · {c.status}
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
