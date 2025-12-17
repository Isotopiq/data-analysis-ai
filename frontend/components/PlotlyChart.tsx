"use client";

import dynamic from "next/dynamic";

export const Plot: any = dynamic(async () => {
  const mod: any = await import("react-plotly.js");
  return mod.default || mod;
}, { ssr: false });
