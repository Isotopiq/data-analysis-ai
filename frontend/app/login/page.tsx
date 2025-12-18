"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, Label, TextInput } from "flowbite-react";

import { apiPost } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [nextPath, setNextPath] = useState("/projects");

  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Avoid Next.js prerender constraints for useSearchParams.
    try {
      const sp = new URLSearchParams(window.location.search);
      const n = sp.get("next");
      if (n) setNextPath(n);
    } catch {
      // ignore
    }
  }, []);

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Sign in</h1>
        <div className="text-sm text-gray-600">Authenticate to access your projects.</div>
      </div>

      {error && <Card className="border-red-200 bg-red-50">{error}</Card>}

      <Card>
        <div className="space-y-3">
          <div>
            <Label htmlFor="username">Username</Label>
            <TextInput id="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="password">Password</Label>
            <TextInput
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <div className="flex justify-end">
            <Button
              disabled={loading}
              onClick={async () => {
                setLoading(true);
                setError(null);
                try {
                  await apiPost(`/auth/login`, { username, password });
                  router.replace(nextPath);
                } catch (e: any) {
                  setError(e?.message || String(e));
                } finally {
                  setLoading(false);
                }
              }}
            >
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </div>
        </div>
      </Card>

      <div className="text-xs text-gray-500">
        Default dev credentials are <code>admin/admin</code> unless overridden by API env.
      </div>
    </div>
  );
}
