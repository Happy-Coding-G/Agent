import { useEffect, useRef, useState } from "react";

import { agentChatStream } from "../api/ptds";
import { useAuth } from "../store/auth";
import { useWorkbench } from "../store/workbench";
import { Tab } from "../types";
import GraphView from "../views/GraphView";

type ToolResult = {
  tool: string;
  result?: any;
};

type SourceItem = {
  doc_id?: string;
  title?: string;
  section?: string;
  score?: number;
  source_type?: string;
  excerpt?: string;
};

type ChatMessage = {
  role: "user" | "assistant" | "status";
  content: string;
  toolResults?: ToolResult[];
  sources?: SourceItem[];
};

const SUGGESTIONS = [
  "查看文件树",
  "显示知识图谱",
  "列出所有资产",
  "生成一份知识资产报告",
  "列出 Markdown 文档",
];

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    detecting_intent: "正在分析意图...",
    planning: "正在规划行动...",
    running: "正在执行...",
    completed: "已完成",
    sources_found: "已找到相关来源",
  };
  return map[status] || status;
}

function toolNameLabel(name: string): string {
  const map: Record<string, string> = {
    file_search: "文件搜索",
    file_manage: "文件管理",
    space_manage: "空间管理",
    markdown_manage: "文档管理",
    graph_manage: "知识图谱",
    asset_manage: "资产管理",
    asset_organize: "资产整理",
    qa_answer: "问答",
    process_document: "文档处理",
    review_document: "文档审查",
    trade_goal: "交易",
    memory_manage: "记忆管理",
    user_config_manage: "用户配置",
    token_usage_query: "Token 查询",
  };
  return map[name] || name;
}

export default function ChatTab({ tab }: { tab: Tab }) {
  const space = useAuth((s) => s.currentSpace);
  const log = useWorkbench((s) => s.log);
  const scrollRef = useRef<HTMLDivElement>(null);

  const storageKey = `chat-history-${tab.id}`;
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) return JSON.parse(raw) as ChatMessage[];
    } catch {}
    return [
      {
        role: "assistant",
        content: "你好，我是 Agent 数据空间助手。你可以通过聊天管理文件、文档、知识图谱、资产和交易。",
      },
    ];
  });
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [panelMode, setPanelMode] = useState<"chat" | "graph">("chat");
  const [activeStatus, setActiveStatus] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(messages));
    } catch {}
  }, [messages, storageKey]);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, activeStatus]);

  const appendStatus = (status: string) => {
    setActiveStatus(statusLabel(status));
  };

  const handleSend = async (textOverride?: string) => {
    const query = (textOverride ?? input).trim();
    if (!query || streaming) return;

    if (!space?.public_id) {
      log("[Chat] select a space first");
      return;
    }

    setMessages((prev) => [...prev, { role: "user", content: query }]);
    if (!textOverride) setInput("");
    setStreaming(true);
    setActiveStatus("正在思考...");

    let assistantContent = "";
    let toolResults: ToolResult[] = [];
    let sources: SourceItem[] = [];

    // 构造最近 3 轮对话历史（user + assistant）
    const history = messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .slice(-6)
      .map((m) => ({
        query: m.role === "user" ? m.content : "",
        answer: m.role === "assistant" ? m.content : "",
      }))
      .filter((m) => m.query || m.answer);

    try {
      await agentChatStream(query, space.public_id, (event) => {
        if (event.type === "token") {
          const token = event.data as string;
          assistantContent += token;
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant") {
              return [...prev.slice(0, -1), { ...last, content: assistantContent, toolResults, sources }];
            }
            return [...prev, { role: "assistant", content: assistantContent, toolResults, sources }];
          });
        } else if (event.type === "status") {
          appendStatus(event.data as string);
        } else if (event.type === "intent") {
          appendStatus(`识别意图: ${event.data}`);
        } else if (event.type === "sources") {
          const src = event.data as SourceItem[] | undefined;
          if (src && src.length > 0) {
            sources = src;
          }
        } else if (event.type === "result") {
          const data = event.data as Record<string, unknown> | undefined;
          if (data && Array.isArray(data.tool_results)) {
            toolResults = data.tool_results as ToolResult[];
          }
          if (data && Array.isArray(data.sources)) {
            sources = data.sources as SourceItem[];
          }
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant") {
              return [...prev.slice(0, -1), { ...last, content: assistantContent || last.content, toolResults, sources }];
            }
            return prev;
          });
        } else if (event.type === "error") {
          const err = event.data as string;
          log(`[Chat] error: ${err}`);
          setMessages((prev) => [...prev, { role: "status", content: `错误: ${err}` }]);
        }
      }, history);
    } catch (e: any) {
      log(`[Chat] request failed: ${e?.message ?? String(e)}`);
      setMessages((prev) => [...prev, { role: "status", content: `请求失败: ${e?.message ?? "network error"}` }]);
    } finally {
      setStreaming(false);
      setActiveStatus(null);
    }
  };

  const renderSources = (sources?: SourceItem[]) => {
    if (!sources || sources.length === 0) return null;
    return (
      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>引用来源：</div>
        <div style={{ display: "grid", gap: 6 }}>
          {sources.map((s, idx) => (
            <div
              key={`${s.doc_id || idx}`}
              style={{
                border: "1px solid var(--border)",
                borderRadius: 6,
                padding: "6px 8px",
                background: "var(--panel-2)",
                fontSize: 11,
              }}
            >
              <div style={{ fontWeight: 600, color: "var(--accent)", marginBottom: 2 }}>
                [{idx + 1}] {s.title || "未知文档"} {s.score !== undefined ? `(score: ${s.score.toFixed(4)})` : ""}
              </div>
              {s.excerpt ? (
                <div style={{ color: "var(--text-muted)", lineHeight: 1.4 }}>{s.excerpt}</div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderToolResults = (toolResults?: ToolResult[]) => {
    if (!toolResults || toolResults.length === 0) return null;
    return (
      <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
        {toolResults.map((tr, idx) => (
          <div
            key={`${tr.tool}-${idx}`}
            style={{
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: "8px 10px",
              background: "var(--panel-2)",
              fontSize: 12,
            }}
          >
            <div style={{ fontWeight: 600, color: "var(--accent)", marginBottom: 4 }}>
              工具调用: {toolNameLabel(tr.tool)}
            </div>
            <ToolResultPreview result={tr.result} />
          </div>
        ))}
      </div>
    );
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
          {panelMode === "chat" ? "Agent-First Chat" : "Graph mode"}
        </div>
      </div>

      {panelMode === "chat" ? (
        <>
          <div className="chat-messages" ref={scrollRef}>
            {messages.map((msg, i) => (
              <div
                key={`${msg.role}-${i}`}
                className={`chat-message ${msg.role === "status" ? "assistant status" : msg.role}`}
              >
                <div className="chat-message-avatar">{msg.role === "user" ? "U" : msg.role === "status" ? "..." : "AI"}</div>
                <div className="chat-message-content">
                  {msg.role === "status" ? (
                    <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>{msg.content}</span>
                  ) : msg.role === "assistant" && streaming && i === messages.length - 1 ? (
                    <>
                      {msg.content}
                      <span className="chat-streaming-cursor" />
                    </>
                  ) : (
                    msg.content
                  )}
                  {msg.role === "assistant" && renderSources(msg.sources)}
                  {msg.role === "assistant" && renderToolResults(msg.toolResults)}
                </div>
              </div>
            ))}
            {activeStatus && (
              <div className="chat-message assistant status">
                <div className="chat-message-avatar">...</div>
                <div className="chat-message-content">
                  <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>{activeStatus}</span>
                </div>
              </div>
            )}
          </div>

          <div style={{ padding: "0 12px" }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="btn btn-ghost"
                  style={{ fontSize: 11, padding: "4px 8px" }}
                  onClick={() => void handleSend(s)}
                  disabled={streaming}
                >
                  {s}
                </button>
              ))}
            </div>
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

function ToolResultPreview({ result }: { result?: any }) {
  if (!result) return <div style={{ color: "var(--text-muted)" }}>无返回数据</div>;

  // File manage list_tree
  if (result.tree && Array.isArray(result.tree)) {
    const count = result.tree.reduce((acc: number, folder: any) => acc + (folder.files?.length || 0), 0);
    return (
      <div style={{ color: "var(--text-muted)" }}>
        目录: {result.tree.length} 个文件夹，{count} 个文件
      </div>
    );
  }

  // Graph manage get
  if (result.graph && (result.graph.nodes || result.graph.edges)) {
    const nodes = result.graph.nodes?.length || 0;
    const edges = result.graph.edges?.length || 0;
    return (
      <div style={{ color: "var(--text-muted)" }}>
        节点: {nodes}，边: {edges}
      </div>
    );
  }

  // Markdown manage list
  if (result.documents && Array.isArray(result.documents)) {
    return <div style={{ color: "var(--text-muted)" }}>文档数: {result.documents.length}</div>;
  }

  // Asset manage list
  if (result.assets && Array.isArray(result.assets)) {
    return <div style={{ color: "var(--text-muted)" }}>资产数: {result.assets.length}</div>;
  }

  // Asset manage generate / get
  if (result.asset) {
    return <div style={{ color: "var(--text-muted)" }}>资产: {result.asset.title || result.asset.asset_id}</div>;
  }

  // Generic success/error
  if (result.success === true && result.message) {
    return <div style={{ color: "var(--text-muted)" }}>{result.message}</div>;
  }
  if (result.success === false && result.error) {
    return <div style={{ color: "var(--danger)" }}>失败: {result.error}</div>;
  }

  return <div style={{ color: "var(--text-muted)" }}>{JSON.stringify(result).slice(0, 200)}</div>;
}
