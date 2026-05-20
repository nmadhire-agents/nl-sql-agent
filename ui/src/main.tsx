import React, { FormEvent, KeyboardEvent, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import { CopilotKit } from "@copilotkit/react-core";
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  CircleStop,
  Code2,
  Database,
  Loader2,
  MessageSquarePlus,
  PanelLeft,
  Play,
  Send,
  Sparkles,
  TerminalSquare,
  User,
  Wand2,
} from "lucide-react";
import "./styles.css";

type Role = "user" | "assistant";

type ReasoningStep = {
  id: string;
  title: string;
  text: string;
  kind: "status" | "tool" | "reasoning" | "error";
};

type ChatMessage = {
  id: string;
  role: Role;
  content: string;
  sql?: string | null;
  traceId?: string | null;
  validationError?: string | null;
  confidence?: string | null;
  reasoning: ReasoningStep[];
  streaming?: boolean;
};

type StreamPayload = {
  type: string;
  title?: string;
  text?: string;
  name?: string;
  answer?: string;
  sql?: string | null;
  trace_id?: string | null;
  validation_error?: string | null;
  confidence?: string | null;
};

const DEFAULT_DB =
  "data/spider/spider_data/database/concert_singer/concert_singer.sqlite";

const suggestions = [
  "How many singers do we have?",
  "Show singers grouped by country.",
  "Which stadium has the highest capacity?",
];

function App() {
  const [dbPath, setDbPath] = useState(DEFAULT_DB);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: crypto.randomUUID(),
      role: "assistant",
      content:
        "Ask a question about the selected SQLite database. I will inspect the schema, validate the SQL, execute the query, and show the answer with the generated SQL.",
      reasoning: [],
      streaming: false,
    },
  ]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const activeTrace = useMemo(
    () => [...messages].reverse().find((message) => message.traceId)?.traceId,
    [messages],
  );

  async function sendQuestion(question: string) {
    const trimmed = question.trim();
    if (!trimmed || isStreaming) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
      reasoning: [],
    };
    const assistantId = crypto.randomUUID();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      reasoning: [
        {
          id: crypto.randomUUID(),
          title: "Queued",
          text: "Sending the question to the local NL-to-SQL agent.",
          kind: "status",
        },
      ],
      streaming: true,
    };

    setMessages((current) => [...current, userMessage, assistantMessage]);
    setInput("");
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch("http://127.0.0.1:8080/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, db_path: dbPath }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Request failed with ${response.status}`);
      }

      await readEventStream(response.body, (payload) => {
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId ? applyStreamPayload(message, payload) : message,
          ),
        );
      });
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  streaming: false,
                  validationError: (error as Error).message,
                  reasoning: [
                    ...message.reasoning,
                    {
                      id: crypto.randomUUID(),
                      title: "Stream failed",
                      text: (error as Error).message,
                      kind: "error",
                    },
                  ],
                }
              : message,
          ),
        );
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }

  function stopStreaming() {
    abortRef.current?.abort();
    setIsStreaming(false);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendQuestion(input);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendQuestion(input);
    }
  }

  return (
    <CopilotKit runtimeUrl="http://127.0.0.1:8080/api/chat">
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand-row">
            <div className="brand-mark">
              <Database size={20} />
            </div>
            <div>
              <div className="brand-title">NL-SQL Agent</div>
              <div className="brand-subtitle">SQLite harness</div>
            </div>
          </div>

          <button className="new-chat" type="button" onClick={() => setMessages([])}>
            <MessageSquarePlus size={17} />
            New chat
          </button>

          <section className="sidebar-section">
            <label htmlFor="dbPath">SQLite database</label>
            <textarea
              id="dbPath"
              className="db-input"
              value={dbPath}
              onChange={(event) => setDbPath(event.target.value)}
              spellCheck={false}
              rows={4}
            />
          </section>

          <section className="sidebar-section">
            <div className="section-title">Try a prompt</div>
            <div className="suggestion-list">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="suggestion"
                  onClick={() => void sendQuestion(suggestion)}
                  disabled={isStreaming}
                >
                  <Wand2 size={15} />
                  {suggestion}
                </button>
              ))}
            </div>
          </section>

          <div className="sidebar-footer">
            <div className="status-pill">
              <span className="live-dot" />
              Local services
            </div>
            {activeTrace ? <div className="trace-small">Trace {activeTrace}</div> : null}
          </div>
        </aside>

        <main className="chat-column">
          <header className="topbar">
            <div className="topbar-title">
              <PanelLeft size={18} />
              <span>SQL Analyst</span>
            </div>
            <div className="topbar-actions">
              <span className="model-badge">
                <Sparkles size={15} />
                Agents SDK
              </span>
              <span className="model-badge">
                <TerminalSquare size={15} />
                Streaming
              </span>
            </div>
          </header>

          <section className="messages" aria-live="polite">
            {messages.length === 0 ? (
              <EmptyState onPick={(question) => void sendQuestion(question)} />
            ) : (
              messages.map((message) => <MessageView key={message.id} message={message} />)
            )}
          </section>

          <form className="composer-wrap" onSubmit={handleSubmit}>
            <div className="composer">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question about the SQLite database..."
                rows={1}
                disabled={isStreaming}
              />
              {isStreaming ? (
                <button className="icon-button stop" type="button" onClick={stopStreaming} aria-label="Stop response">
                  <CircleStop size={20} />
                </button>
              ) : (
                <button className="icon-button send" type="submit" disabled={!input.trim()} aria-label="Send question">
                  <Send size={18} />
                </button>
              )}
            </div>
            <div className="composer-hint">
              Press Enter to send, Shift+Enter for a new line. SQL is validated before execution.
            </div>
          </form>
        </main>
      </div>
    </CopilotKit>
  );
}

function EmptyState({ onPick }: { onPick: (question: string) => void }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <Bot size={28} />
      </div>
      <h1>What do you want to know?</h1>
      <div className="empty-grid">
        {suggestions.map((suggestion) => (
          <button key={suggestion} type="button" onClick={() => onPick(suggestion)}>
            <Play size={15} />
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageView({ message }: { message: ChatMessage }) {
  const isAssistant = message.role === "assistant";
  return (
    <article className={`message ${message.role}`}>
      <div className="avatar">{isAssistant ? <Bot size={18} /> : <User size={18} />}</div>
      <div className="message-body">
        <div className="message-name">{isAssistant ? "SQL Analyst" : "You"}</div>
        {message.content ? (
          <div className="message-content">{message.content}</div>
        ) : message.streaming ? (
          <div className="typing-row">
            <Loader2 className="spin" size={16} />
            Working through schema, SQL, and results...
          </div>
        ) : null}

        {message.reasoning.length > 0 ? <ReasoningPanel steps={message.reasoning} streaming={Boolean(message.streaming)} /> : null}
        {message.sql ? <SqlBlock sql={message.sql} /> : null}
        {message.validationError ? <div className="error-box">{message.validationError}</div> : null}
        {message.traceId || message.confidence ? (
          <div className="meta-row">
            {message.confidence ? (
              <span>
                <CheckCircle2 size={14} />
                Confidence: {message.confidence}
              </span>
            ) : null}
            {message.traceId ? <span>Trace: {message.traceId}</span> : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function ReasoningPanel({ steps, streaming }: { steps: ReasoningStep[]; streaming: boolean }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="reasoning-panel">
      <button type="button" className="reasoning-header" onClick={() => setOpen((value) => !value)}>
        <span>
          {streaming ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
          Agent reasoning and tool trace
        </span>
        <ChevronDown className={open ? "chevron open" : "chevron"} size={17} />
      </button>
      {open ? (
        <div className="reasoning-list">
          {steps.map((step) => (
            <div key={step.id} className={`reasoning-step ${step.kind}`}>
              <div className="step-dot" />
              <div>
                <div className="step-title">{step.title}</div>
                <div className="step-text">{step.text}</div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SqlBlock({ sql }: { sql: string }) {
  return (
    <div className="sql-card">
      <div className="sql-header">
        <span>
          <Code2 size={15} />
          Generated SQLite
        </span>
      </div>
      <pre>
        <code>{sql}</code>
      </pre>
    </div>
  );
}

async function readEventStream(stream: ReadableStream<Uint8Array>, onPayload: (payload: StreamPayload) => void) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      const dataLine = event
        .split("\n")
        .find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      onPayload(JSON.parse(dataLine.slice(5).trim()) as StreamPayload);
    }
  }
}

function applyStreamPayload(message: ChatMessage, payload: StreamPayload): ChatMessage {
  if (payload.type === "answer_delta") {
    return { ...message, content: message.content + (payload.text ?? "") };
  }
  if (payload.type === "sql") {
    return { ...message, sql: payload.sql };
  }
  if (payload.type === "validation_error") {
    return { ...message, validationError: payload.text ?? "Validation failed." };
  }
  if (payload.type === "done") {
    return {
      ...message,
      streaming: false,
      content: payload.answer || message.content,
      sql: payload.sql ?? message.sql,
      traceId: payload.trace_id ?? message.traceId,
      validationError: payload.validation_error ?? message.validationError,
    };
  }
  if (payload.type === "answer_start") {
    return {
      ...message,
      traceId: payload.trace_id ?? message.traceId,
      confidence: payload.confidence ?? message.confidence,
    };
  }
  if (["status", "tool_call", "tool_output", "reasoning", "reasoning_delta", "error"].includes(payload.type)) {
    const kind: ReasoningStep["kind"] =
      payload.type === "error" ? "error" : payload.type.startsWith("tool") ? "tool" : payload.type.startsWith("reasoning") ? "reasoning" : "status";
    return {
      ...message,
      validationError: payload.type === "error" ? payload.text ?? message.validationError : message.validationError,
      reasoning: [
        ...message.reasoning,
        {
          id: crypto.randomUUID(),
          title: payload.title ?? readableEventTitle(payload.type),
          text: payload.text ?? "",
          kind,
        },
      ],
      streaming: payload.type === "error" ? false : message.streaming,
    };
  }
  return message;
}

function readableEventTitle(type: string) {
  if (type === "tool_call") return "Calling tool";
  if (type === "tool_output") return "Tool output";
  if (type === "reasoning_delta") return "Reasoning summary";
  return "Agent update";
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
