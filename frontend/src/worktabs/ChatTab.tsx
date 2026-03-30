import { useEffect, useRef, useState } from "react";

import { agentChatStream } from "../api/ptds";
import { useAuth } from "../store/auth";
import { useWorkbench } from "../store/workbench";
import { Tab } from "../types";
import GraphView from "../views/GraphView";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export default function ChatTab({ tab }: { tab: Tab }) {
  const space = useAuth((s) => s.currentSpace);
  const log = useWorkbench((s) => s.log);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [panelMode, setPanelMode] = useState<"chat" | "graph">("chat");

  useEffect(() => {
    if (messages.length === 0) {
      setMessages([
        {
          role: "assistant",
          content: "你好，我是知识助手。你可以基于当前空间文档进行提问。",
        },
      ]);
    }
  }, [messages.length]);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  const handleSend = async () => {
    const query = input.trim();
    if (!query || streaming) return;

    if (!space?.public_id) {
      log("[Chat] select a space first");
      return;
    }

    setMessages((prev) => [...prev, { role: "user", content: query }, { role: "assistant", content: "" }]);
    setInput("");
    setStreaming(true);

    try {
      await agentChatStream(
        query,
        space.public_id,
        (event) => {
          if (event.type === "token") {
            const token = event.data as string;
            setMessages((prev) => {
              if (prev.length === 0) return prev;
              const last = prev[prev.length - 1];
              if (last.role !== "assistant") return prev;
              return [...prev.slice(0, -1), { ...last, content: last.content + token }];
            });
          }
        },
      );
    } catch (e: any) {
      log(`[Chat] request failed: ${e?.message ?? String(e)}`);
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const last = prev[prev.length - 1];
        if (last.role !== "assistant") return prev;
        return [...prev.slice(0, -1), { ...last, content: `${last.content}\n\nError: ${e?.message ?? "request failed"}` }];
      });
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="col" style={{ minHeight: 0, gap: 10 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          padding: "8px 12px 0",
        }}
      >
        <div style={{ display: "flex", gap: 6 }}>
          <button
            className="btn btn-ghost"
            onClick={() => setPanelMode("chat")}
            style={panelMode === "chat" ? { background: "var(--accent-light)", borderColor: "var(--accent)" } : undefined}
          >
            Chat
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => setPanelMode("graph")}
            style={panelMode === "graph" ? { background: "var(--accent-light)", borderColor: "var(--accent)" } : undefined}
          >
            Graph
          </button>
        </div>
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {panelMode === "chat" ? "Chat mode" : "Graph mode"}
        </div>
      </div>

      {panelMode === "chat" ? (
        <>
          <div className="chat-messages" ref={scrollRef}>
            {messages.map((msg, i) => (
              <div key={`${msg.role}-${i}`} className={`chat-message ${msg.role}`}>
                <div className="chat-message-avatar">{msg.role === "user" ? "U" : "AI"}</div>
                <div className="chat-message-content">
                  {msg.role === "assistant" && streaming && i === messages.length - 1 ? (
                    <>
                      {msg.content}
                      <span className="chat-streaming-cursor" />
                    </>
                  ) : (
                    msg.content
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="chat-input-area">
            <textarea
              className="chat-input"
              placeholder="输入问题，Ctrl+Enter 发送"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
              disabled={streaming}
              rows={2}
            />
            <button className="chat-send-btn" onClick={() => void handleSend()} disabled={streaming || !input.trim()}>
              {streaming ? "..." : "Send"}
            </button>
          </div>
        </>
      ) : (
        <div style={{ minHeight: 0, flex: 1, overflow: "auto", padding: "0 12px 12px" }}>
          <GraphView mode="display" canvasHeight={460} />
        </div>
      )}
    </div>
  );
}
