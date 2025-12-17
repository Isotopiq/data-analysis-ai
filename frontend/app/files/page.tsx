"use client";

import { useEffect, useState } from "react";
import {
  Button,
  Card,
  FileInput,
  Label,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
} from "flowbite-react";

import { API_BASE_URL, apiGet } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type FileRow = {
  id: string;
  name: string;
  size_bytes: number;
  mime_type: string | null;
  created_at: string;
};

type Preview = { columns: string[]; rows: any[][] };

type Profile = {
  profile: {
    n_rows: number;
    n_cols: number;
    columns: Array<any>;
  };
};

export default function FilesPage() {
  const projectId = useAppStore((s) => s.selectedProjectId);
  const [files, setFiles] = useState<FileRow[]>([]);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<FileRow[]>(`/projects/${projectId}/files`);
      setFiles(data);
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

  async function loadFileDetails(fileId: string) {
    if (!projectId) return;
    setSelectedFileId(fileId);
    setPreview(null);
    setProfile(null);
    setLoading(true);
    setError(null);
    try {
      const pvw = await apiGet<Preview>(`/projects/${projectId}/files/${fileId}/preview`);
      const prof = await apiGet<Profile>(`/projects/${projectId}/files/${fileId}/profile`);
      setPreview(pvw);
      setProfile(prof);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

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
          <h1 className="text-2xl font-semibold">Files</h1>
          <div className="text-sm text-gray-600">Upload CSV/XLSX/Parquet and view profiling + preview.</div>
        </div>
        <Button color="gray" onClick={refresh} disabled={loading}>
          Refresh
        </Button>
      </div>

      {error && <Card className="border-red-200 bg-red-50">{error}</Card>}

      <Card>
        <div className="space-y-2">
          <Label htmlFor="file">Upload file</Label>
          <div className="flex gap-2">
            <FileInput
              id="file"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                setLoading(true);
                setError(null);
                try {
                  const form = new FormData();
                  form.append("file", f);
                  const res = await fetch(
                    `${API_BASE_URL}/projects/${projectId}/files/upload`,
                    { method: "POST", body: form }
                  );
                  if (!res.ok) throw new Error(await res.text());
                  await refresh();
                } catch (err: any) {
                  setError(err?.message || String(err));
                } finally {
                  setLoading(false);
                  (e.target as HTMLInputElement).value = "";
                }
              }}
            />
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <div className="text-sm font-semibold">Uploaded files</div>
          <Table hoverable>
            <TableHead>
              <TableHeadCell>Name</TableHeadCell>
              <TableHeadCell>Size</TableHeadCell>
              <TableHeadCell>Uploaded</TableHeadCell>
            </TableHead>
            <TableBody className="divide-y">
              {files.map((f) => (
                <TableRow
                  key={f.id}
                  className={f.id === selectedFileId ? "bg-gray-50" : "bg-white"}
                  onClick={() => loadFileDetails(f.id)}
                >
                  <TableCell className="font-medium text-gray-900">
                    {f.name}
                  </TableCell>
                  <TableCell className="text-sm text-gray-600">
                    {(f.size_bytes / 1024).toFixed(1)} KB
                  </TableCell>
                  <TableCell className="text-sm text-gray-600">
                    {new Date(f.created_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>

        <Card>
          <div className="text-sm font-semibold">Preview</div>
          {!preview ? (
            <div className="mt-2 text-sm text-gray-600">Select a file to load preview.</div>
          ) : (
            <div className="mt-2 overflow-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr>
                    {preview.columns.map((c) => (
                      <th key={c} className="border-b px-2 py-1 text-left font-semibold">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((r, i) => (
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
          )}
        </Card>
      </div>

      <Card>
        <div className="text-sm font-semibold">Profile</div>
        {!profile ? (
          <div className="mt-2 text-sm text-gray-600">Select a file to load profiling.</div>
        ) : (
          <div className="mt-3 space-y-2">
            <div className="text-sm text-gray-700">
              Rows: <span className="font-medium">{profile.profile.n_rows}</span>, Columns:{" "}
              <span className="font-medium">{profile.profile.n_cols}</span>
            </div>
            <Table>
              <TableHead>
                <TableHeadCell>Column</TableHeadCell>
                <TableHeadCell>Type</TableHeadCell>
                <TableHeadCell>Missing</TableHeadCell>
                <TableHeadCell>Notes</TableHeadCell>
              </TableHead>
              <TableBody className="divide-y">
                {profile.profile.columns.map((c: any) => (
                  <TableRow key={c.name}>
                    <TableCell className="font-medium text-gray-900">{c.name}</TableCell>
                    <TableCell className="text-sm text-gray-600">{c.dtype}</TableCell>
                    <TableCell className="text-sm text-gray-600">
                      {c.missing} ({(c.missing_pct * 100).toFixed(1)}%)
                    </TableCell>
                    <TableCell className="text-xs text-gray-600">
                      {c.mean !== undefined ? `mean=${c.mean ?? ""} min=${c.min ?? ""} max=${c.max ?? ""}` : ""}
                      {c.top_values ? `top=${c.top_values[0]?.value ?? ""}` : ""}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  );
}
