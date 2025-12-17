"use client";

import dynamic from "next/dynamic";

export const Monaco = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
});
