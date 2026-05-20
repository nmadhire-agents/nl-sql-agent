import React from "react";
import ReactDOM from "react-dom/client";
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotPopup } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";

function App() {
  return (
    <CopilotKit runtimeUrl="http://127.0.0.1:8080/api/chat">
      <div style={{ minHeight: "100vh", background: "linear-gradient(135deg,#0f172a,#1e293b)", color: "white", padding: 32 }}>
        <h1 style={{ fontSize: 36, marginBottom: 8 }}>NL → SQL Copilot</h1>
        <p style={{ opacity: 0.8 }}>Ask questions, inspect answer, SQL, and agent reasoning.</p>
        <CopilotPopup
          instructions="Use db_path from user context and answer with answer/sql/reasoning."
          labels={{ title: "SQL Analyst", initial: "Ask any database question" }}
          defaultOpen
        />
      </div>
    </CopilotKit>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
