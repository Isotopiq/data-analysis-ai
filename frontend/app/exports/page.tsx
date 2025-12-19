"use client";

import { Button, Card } from "flowbite-react";

import { API_BASE_URL } from "@/lib/api";
import { useAppStore } from "@/lib/store";

export default function ExportsPage() {
  const projectId = useAppStore((s) => s.selectedProjectId);

  if (!projectId) {
    return (
      <Card>
        <div className="text-sm text-gray-700">Select a project first (Projects page).</div>
      </Card>
    );
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Exports</h1>
        <div className="text-sm text-gray-600">Export the current workspace to a reproducible notebook.</div>
      </div>

      <Card>
        <div className="space-y-2">
          <div className="text-sm text-gray-700">Export workspace to <code>.ipynb</code>.</div>
          <Button
            onClick={async () => {
              const res = await fetch(`${API_BASE_URL}/projects/${projectId}/export/ipynb`, {
                method: "POST",
                credentials: "include",
              });
              if (!res.ok) throw new Error(await res.text());
              const blob = await res.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "workspace.ipynb";
              document.body.appendChild(a);
              a.click();
              a.remove();
              URL.revokeObjectURL(url);
            }}
          >
            Download .ipynb
          </Button>
        </div>
      </Card>
    </div>
  );
}
