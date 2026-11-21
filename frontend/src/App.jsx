import { useEffect, useRef, useState } from "react";

// Set at build time: VITE_API_URL=https://your-backend.example.com
const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

// A brand-new session id on every page load.
const newSessionId = () =>
  "s-" + (crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Math.random().toString(36).slice(2, 10));

function describeError(status, body) {
  if (status === 503) return "All AI providers are unavailable right now. Please try again in a moment.";
  if (status === 422) {
    const d = body && body.detail;
    if (Array.isArray(d)) return "Invalid request: " + d.map((e) => e.msg).join("; ");
    return "Invalid request: " + (typeof d === "string" ? d : "please check your message.");
  }
  if (body && typeof body.detail === "string") return body.detail;
  return `Something went wrong (HTTP ${status}). Please try again.`;
}

function AssistantMessage({ m }) {
  const md = m.metadata;
  return (
    <div className="row assistant" data-testid="assistant-message">
      <div className="bubble">
        <div className="text">{m.content}</div>
        <div className="meta">
          <span className="chip">
            <b>Source</b>{" "}
            <span
              data-testid="meta-source"
              className={md.resolution_source === "LLM_CACHE" ? "cache" : "live"}
            >
              {md.resolution_source}
            </span>
          </span>
          <span className="chip">
            <b>Model</b> <span data-testid="meta-model">{md.model}</span>
          </span>
          <span className="chip">
            <b>Latency</b> <span data-testid="meta-latency">{md.latency_ms} ms</span>
          </span>
          <span className="chip">
            <b>In</b> <span data-testid="meta-input-tokens">{md.input_tokens}</span>
          </span>
          <span className="chip">
            <b>Out</b> <span data-testid="meta-output-tokens">{md.output_tokens}</span>
          </span>
          {md.key_id && (
            <span className="chip subtle">
              {md.key_id}
              {md.fallback_attempts > 0 ? ` · ${md.fallback_attempts} fallback` : ""}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [sessionId] = useState(newSessionId);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const push = (m) => setMessages((prev) => [...prev, { id: prev.length + 1, ...m }]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    push({ role: "user", content: text });
    setLoading(true);

    const body = { session_id: sessionId, message: text };
    if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      let data = null;
      try {
        data = await res.json();
      } catch {
        /* non-JSON body */
      }
      if (res.ok && data && data.reply) {
        push({ role: "assistant", content: data.reply, metadata: data.metadata });
      } else {
        push({ role: "error", content: describeError(res.status, data) });
      }
    } catch {
      push({ role: "error", content: "Cannot reach the server. Check your connection and try again." });
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="app">
      <header>
        <h1>LLM Chatbot</h1>
        <span className="session">session {sessionId}</span>
      </header>

      <details className="sys">
        <summary>System prompt (optional)</summary>
        <textarea
          data-testid="system-prompt-input"
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          placeholder="e.g. You are a pirate. Answer in pirate speak."
          rows={2}
        />
      </details>

      <main className="chat">
        {messages.length === 0 && (
          <p className="empty">Ask anything to start the conversation.</p>
        )}
        {messages.map((m) =>
          m.role === "assistant" ? (
            <AssistantMessage key={m.id} m={m} />
          ) : m.role === "error" ? (
            <div key={m.id} className="row assistant" role="alert">
              <div className="bubble errorbox">{m.content}</div>
            </div>
          ) : (
            <div key={m.id} className="row user">
              <div className="bubble">{m.content}</div>
            </div>
          )
        )}
        {loading && (
          <div className="row assistant">
            <div className="bubble typing">Thinking…</div>
          </div>
        )}
        <div ref={endRef} />
      </main>

      <footer>
        <textarea
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a message…  (Enter to send, Shift+Enter for a new line)"
          rows={2}
        />
        <button data-testid="send-button" onClick={send} disabled={loading}>
          Send
        </button>
      </footer>
    </div>
  );
}
