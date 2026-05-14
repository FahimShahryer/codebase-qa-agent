"use client";

import { useCallback, useEffect, useState } from "react";

import Chat from "./components/Chat";
import RepoSelector from "./components/RepoSelector";
import SessionSidebar from "./components/SessionSidebar";

function newSessionId(): string {
  // crypto.randomUUID is available in modern browsers + Node 19+
  return (typeof crypto !== "undefined" && "randomUUID" in crypto)
    ? crypto.randomUUID()
    : `s-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const LS_SESSION_KEY = "ajentica.session_id";
const LS_REPO_KEY = "ajentica.repo";

export default function Page() {
  const [sessionId, setSessionId] = useState<string>("");
  const [repo, setRepo] = useState<string>("");
  const [reloadKey, setReloadKey] = useState<number>(0);

  // Bootstrap session_id + repo from localStorage on first mount
  useEffect(() => {
    const sid = localStorage.getItem(LS_SESSION_KEY) || newSessionId();
    const r = localStorage.getItem(LS_REPO_KEY) || "";
    setSessionId(sid);
    setRepo(r);
    localStorage.setItem(LS_SESSION_KEY, sid);
  }, []);

  const handleSelectSession = useCallback((id: string) => {
    setSessionId(id);
    localStorage.setItem(LS_SESSION_KEY, id);
  }, []);

  const handleNewChat = useCallback(() => {
    const sid = newSessionId();
    setSessionId(sid);
    localStorage.setItem(LS_SESSION_KEY, sid);
  }, []);

  const handleRepoChange = useCallback((r: string) => {
    setRepo(r);
    localStorage.setItem(LS_REPO_KEY, r);
  }, []);

  const bumpSidebar = useCallback(() => setReloadKey((k) => k + 1), []);

  if (!sessionId) return null;  // wait for hydration

  return (
    <div style={{ display: "flex", height: "100vh", background: "#fafafa" }}>
      <SessionSidebar
        currentSessionId={sessionId}
        onSelect={handleSelectSession}
        onNew={handleNewChat}
        reloadKey={reloadKey}
      />
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <header
          style={{
            padding: "0.75rem 2rem",
            borderBottom: "1px solid #d0d7de",
            background: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <h1 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 600 }}>
            Codebase Q&amp;A Agent
          </h1>
          <RepoSelector value={repo} onChange={handleRepoChange} />
        </header>
        {repo ? (
          <Chat sessionId={sessionId} repo={repo} onSessionUsed={bumpSidebar} />
        ) : (
          <div style={{ padding: "2rem", color: "#57606a" }}>
            No indexed repos available. Run <code>docker compose exec backend
            python -m src.cli index --repo flask</code> first.
          </div>
        )}
      </div>
    </div>
  );
}
