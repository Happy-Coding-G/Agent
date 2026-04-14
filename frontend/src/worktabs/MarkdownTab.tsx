import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getMarkdownDoc } from "../api/ptds";
import { useAuth } from "../store/auth";
import { useWorkbench } from "../store/workbench";
import { Tab } from "../types";

export default function MarkdownTab({ tab }: { tab: Tab }) {
  const authSpace = useAuth((s) => s.currentSpace);
  const log = useWorkbench((s) => s.log);

  const payloadDocId = typeof tab.payload?.docId === "string" ? tab.payload.docId : undefined;
  const payloadSpaceId = typeof tab.payload?.spacePublicId === "string" ? tab.payload.spacePublicId : undefined;
  const incomingContent = typeof tab.payload?.content === "string" ? tab.payload.content : undefined;

  const spacePublicId = payloadSpaceId ?? authSpace?.public_id;
  const isRemoteDoc = Boolean(payloadDocId && spacePublicId);

  const [title, setTitle] = useState("Markdown");
  const [content, setContent] = useState<string>(incomingContent ?? "_(empty markdown document)_");
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState<string>(isRemoteDoc ? "Remote" : "Local draft");

  useEffect(() => {
    if (incomingContent !== undefined) {
      setContent(incomingContent);
    }
  }, [incomingContent, tab.id]);

  useEffect(() => {
    if (!isRemoteDoc || !payloadDocId || !spacePublicId) {
      return;
    }

    let active = true;
    setLoading(true);
    setStatusText("Loading...");

    getMarkdownDoc(spacePublicId, payloadDocId)
      .then((doc) => {
        if (!active) return;
        setTitle(doc.title || "Markdown");
        setContent(doc.markdown_text || "_(empty markdown document)_");
        setStatusText(`Loaded · chunks ${doc.chunk_count}`);
      })
      .catch((err: any) => {
        if (!active) return;
        setStatusText("Load failed");
        log(`[Markdown] load failed: ${err?.message ?? String(err)}`);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [isRemoteDoc, payloadDocId, spacePublicId, log]);

  return (
    <div className="col" style={{ minHeight: 0, gap: 8 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="row" style={{ gap: 6, alignItems: "center", flex: 1 }}>
          <input
            className="input"
            style={{ maxWidth: 360, fontSize: 12, background: "transparent" }}
            value={title}
            readOnly
            placeholder="Document title"
          />
        </div>

        <div className="row" style={{ gap: 8, alignItems: "center" }}>
          <span className="badge">{statusText}</span>
          <span className="badge" style={{ color: "var(--text-muted)", borderColor: "var(--text-muted)" }}>
            View only
          </span>
        </div>
      </div>

      {loading ? (
        <div style={{ color: "var(--text-muted)", padding: 12 }}>Loading markdown...</div>
      ) : (
        <div className="md-preview" style={{ minHeight: 0, flex: 1, overflow: "auto" }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
