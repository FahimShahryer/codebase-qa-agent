// Step 1 stub. The real chat UI ships in Step 9 (Chat, ThinkingTrace, etc.).
export default function Page() {
  return (
    <main style={{ padding: "3rem 2rem", maxWidth: 720, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.75rem", marginBottom: "0.5rem" }}>
        Codebase Q&amp;A Agent
      </h1>
      <p style={{ color: "#555", lineHeight: 1.6 }}>
        Backend health check is the only wired endpoint at this step. Try:
      </p>
      <pre
        style={{
          background: "#fff",
          border: "1px solid #e3e3e3",
          padding: "0.75rem 1rem",
          borderRadius: 6,
          fontSize: "0.85rem",
          overflow: "auto",
        }}
      >
        curl http://localhost:8000/health
      </pre>
      <p style={{ color: "#888", fontSize: "0.85rem", marginTop: "2rem" }}>
        The chat interface is built in Step 9.
      </p>
    </main>
  );
}
