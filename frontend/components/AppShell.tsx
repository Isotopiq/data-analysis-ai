"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Navbar, NavbarBrand, Sidebar, SidebarItem, SidebarItemGroup, SidebarItems } from "flowbite-react";
import {
  HiChatAlt2,
  HiCollection,
  HiDatabase,
  HiDocumentText,
  HiFolderOpen,
  HiOutlineCog,
  HiPlay,
} from "react-icons/hi";

import { useAppStore } from "@/lib/store";
import { ProjectContextDrawer } from "@/components/ProjectContextDrawer";

const navItems = [
  { href: "/projects", label: "Projects", icon: HiCollection },
  { href: "/chat", label: "Chat", icon: HiChatAlt2 },
  { href: "/files", label: "Files", icon: HiFolderOpen },
  { href: "/sql", label: "SQL", icon: HiDatabase },
  { href: "/workspace", label: "Workspace", icon: HiPlay },
  { href: "/exports", label: "Exports", icon: HiDocumentText },
  { href: "/settings", label: "Settings", icon: HiOutlineCog },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const selectedProject = useAppStore((s) => s.selectedProject);

  return (
    <div className="h-screen w-screen bg-gray-50 text-gray-900">
      <Navbar fluid rounded className="border-b bg-white">
        <NavbarBrand as={Link} href="/projects">
          <span className="self-center whitespace-nowrap text-xl font-semibold">
            Unified Data App
          </span>
        </NavbarBrand>
        <div className="flex items-center gap-3">
          <div className="hidden md:block text-sm text-gray-600">
            <span className="font-medium">Project:</span>{" "}
            {selectedProject ? selectedProject.name : "(none)"}
          </div>
          {selectedProject && (
            <div className="hidden md:block text-xs text-gray-500">
              LLM: {selectedProject.llm_provider}/{selectedProject.llm_model}
            </div>
          )}
        </div>
      </Navbar>

      <div className="flex h-[calc(100vh-56px)]">
        <aside className="w-64 border-r bg-white">
          <Sidebar aria-label="Sidebar">
            <SidebarItems>
              <SidebarItemGroup>
                {navItems.map((item) => {
                  const active = pathname.startsWith(item.href);
                  return (
                    <SidebarItem
                      key={item.href}
                      as={Link}
                      href={item.href}
                      icon={item.icon}
                      className={active ? "bg-gray-100" : ""}
                    >
                      {item.label}
                    </SidebarItem>
                  );
                })}
              </SidebarItemGroup>
            </SidebarItems>
          </Sidebar>
        </aside>

        <main className="flex-1 overflow-auto p-6">{children}</main>

        <aside className="hidden xl:block w-80 border-l bg-white p-4">
          <div className="text-sm font-semibold">Context</div>
          <div className="mt-3">
            <ProjectContextDrawer />
          </div>
        </aside>
      </div>
    </div>
  );
}
