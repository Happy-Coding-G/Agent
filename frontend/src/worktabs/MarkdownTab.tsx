import { useState } from "react";
import { Tab } from "../types";

export default function MarkdownTab({ tab }: { tab: Tab }) {
  const [content, setContent] = useState(tab.payload?.content as string ?? "# 标题\n\n内容...");

  return (
    <div className="col" style={{ minHeight: 0 }}>
      <div style={{ flex: 1, overflow: "auto", padding: "16px" }}>
        <textarea
          style={{
            width: "100%",
            height: "100%",
            minHeight: 200,
            background: "var(--panel-2)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            color: "var(--text)",
            padding: "12px",
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            resize: "none",
            outline: "none",
          }}
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      </div>
    </div>
  );
}