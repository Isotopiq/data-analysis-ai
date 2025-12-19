"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  TextInput,
} from "flowbite-react";

import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type Project = {
  id: string;
  name: string;
  llm_provider: "ollama" | "api";
  llm_model: string;
  llm_temperature: number;
  api_base_url: string | null;
  allow_writes: boolean;
};

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState("New Project");

  const selectedProjectId = useAppStore((s) => s.selectedProjectId);
  const setSelectedProjectId = useAppStore((s) => s.setSelectedProjectId);
  const setSelectedProject = useAppStore((s) => s.setSelectedProject);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<Project[]>("/projects");
      setProjects(data);
      const selected = data.find((p) => p.id === selectedProjectId) || null;
      setSelectedProject(selected);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = useMemo(
    () => projects.find((p) => p.id === selectedProjectId) || null,
    [projects, selectedProjectId]
  );

  return (
    <div className="max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Projects</h1>
          <div className="text-sm text-gray-600">
            Create and select a project to scope chat, files, SQL, and workspace.
          </div>
        </div>
        <div className="flex gap-2">
          <Button color="gray" onClick={refresh} disabled={loading}>
            Refresh
          </Button>
          <Button onClick={() => setOpen(true)}>Create project</Button>
        </div>
      </div>

      {error && <Card className="border-red-200 bg-red-50">{error}</Card>}

      <Card>
        <Table hoverable>
          <TableHead>
            <TableHeadCell>Name</TableHeadCell>
            <TableHeadCell>LLM</TableHeadCell>
            <TableHeadCell>SQL writes</TableHeadCell>
            <TableHeadCell className="w-40">Actions</TableHeadCell>
          </TableHead>
          <TableBody className="divide-y">
            {projects.map((p) => (
              <TableRow
                key={p.id}
                className={
                  p.id === selectedProjectId ? "bg-gray-50" : "bg-white"
                }
              >
                <TableCell className="font-medium text-gray-900">
                  {p.name}
                </TableCell>
                <TableCell className="text-sm text-gray-600">
                  {p.llm_provider}/{p.llm_model}
                </TableCell>
                <TableCell className="text-sm text-gray-600">
                  {p.allow_writes ? "Allowed" : "Read-only"}
                </TableCell>
                <TableCell>
                  <div className="flex gap-2">
                    <Button
                      size="xs"
                      color={p.id === selectedProjectId ? "gray" : "blue"}
                      onClick={() => {
                        setSelectedProjectId(p.id);
                        setSelectedProject(p);
                      }}
                    >
                      {p.id === selectedProjectId ? "Selected" : "Select"}
                    </Button>
                    <Button
                      size="xs"
                      color="failure"
                      onClick={async () => {
                        if (!confirm(`Delete project '${p.name}'?`)) return;
                        await apiDelete(`/projects/${p.id}`);
                        if (p.id === selectedProjectId) {
                          setSelectedProjectId(null);
                          setSelectedProject(null);
                        }
                        await refresh();
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {!loading && projects.length === 0 && (
          <div className="p-4 text-sm text-gray-600">No projects yet.</div>
        )}
      </Card>

      <Modal show={open} onClose={() => setOpen(false)}>
        <ModalHeader>Create project</ModalHeader>
        <ModalBody>
          <div className="space-y-2">
            <Label htmlFor="name">Project name</Label>
            <TextInput
              id="name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </div>
        </ModalBody>
        <ModalFooter>
          <Button
            onClick={async () => {
              const p = await apiPost<Project>("/projects", { name: newName });
              setOpen(false);
              setNewName("New Project");
              setSelectedProjectId(p.id);
              setSelectedProject(p);
              await refresh();
            }}
          >
            Create
          </Button>
          <Button color="gray" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>

      {selected && (
        <Card>
          <div className="text-sm text-gray-600">
            Current project: <span className="font-medium">{selected.name}</span>
          </div>
        </Card>
      )}
    </div>
  );
}
