"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ProjectSummary = {
  id: string;
  name: string;
  llm_provider: "ollama" | "api";
  llm_model: string;
  allow_writes: boolean;
};

type AppState = {
  selectedProjectId: string | null;
  setSelectedProjectId: (id: string | null) => void;

  selectedProject: ProjectSummary | null;
  setSelectedProject: (p: ProjectSummary | null) => void;

  sqlDraft: string;
  setSqlDraft: (sql: string) => void;
};

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      selectedProjectId: null,
      setSelectedProjectId: (id) => set({ selectedProjectId: id }),

      selectedProject: null,
      setSelectedProject: (p) => set({ selectedProject: p }),

      sqlDraft: "",
      setSqlDraft: (sql) => set({ sqlDraft: sql }),
    }),
    { name: "unified-data-app" }
  )
);
