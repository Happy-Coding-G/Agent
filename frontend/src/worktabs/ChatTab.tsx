import { useState, useRef, useEffect } from "react";
import { Tab } from "../types";
import { streamSSE } from "../api/client";
import { useWorkbench } from "../store/workbench";
import { useAuth } from "../store/auth";

export default function ChatTab({ tab }: { tab: Tab }) {
  const space = useAuth(s => s.currentSpace);
  const log = useWorkbench(s => s.log);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);

  useEffect(() => {
    if (messages.length === 0) {
      setMessages([
        { role: "assistant", content: "你好！我是 PTDS AI 助手。你可以问我关于空间、文件或知识图谱的问题。" },
      ]);
    }
  }, [messages.length]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || streaming) return;
    if (!space?.id) {
      log("[Chat] 请先选择空间");
      return;
    }

    const userMsg = { role: "user", content: input.trim() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setStreaming(true);

    const assistantIndex = messages.length + 1;
    setMessages(prev => [...prev, { role: "assistant", content: "" }]);

    try {
      await streamSSE("/api/v1/chat", { space_id: space.id, query: userMsg.content }, (dataLine) => {
        if (dataLine.startsWith("data:")) {
          const delta = dataLine.slice(5).trim();
          if (delta === "[DONE]") {
            return;
          }
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last.role === "assistant") {
              return [...prev.slice(0, -1), { ...last, content: last.content + delta }];
            }
            return prev;
          });
        }
      });
    } catch (e: any) {
      log(`[Chat] 错误: ${e?.message ?? String(e)}`);
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last.role === "assistant") {
          return [...prev.slice(0, -1), { ...last, content: last.content + `\n\n❌ ${e?.message ?? "请求失败"}` }];
        }
        return prev;
      });
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="col" style={{ minHeight: 0 }}>
      <div className="chat-messages" ref={scrollRef}>
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message ${msg.role}`}>
            <div className="chat-message-avatar">
              {msg.role === "user" ? "👤" : "🤖"}
            </div>
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
          placeholder="输入消息... (Ctrl+Enter 发送)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              handleSend();
            }
          }}
          disabled={streaming}
          rows={2}
        />
        <button
          className="chat-send-btn"
          onClick={handleSend}
          disabled={streaming || !input.trim()}
        >
          {streaming ? "⏳" : "➤"}
        </button>
      </div>
    </div>
  );
}