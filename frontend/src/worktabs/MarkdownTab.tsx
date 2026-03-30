import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getMarkdownDoc, saveMarkdownDoc } from "../api/ptds";
import { useAuth } from "../store/auth";
import { useWorkbench } from "../store/workbench";
import { Tab } from "../types";

type ViewMode = "split" | "edit" | "preview";

const DEFAULT_CONTENT = [
  "# Markdown",
  "",
  "This tab supports **view / edit / save** with vector re-index on save.",
  "",
  "## Tips",
  "",
  "- Click Save to persist changes",
  "- In remote doc mode, vectors are updated automatically",
].join("\n");

export default function MarkdownTab({ tab }: { tab: Tab }) {
  const authSpace = useAuth((s) => s.currentSpace);
  const log = useWorkbench((s) => s.log);

  const payloadDocId = typeof tab.payload?.docId === "string" ? tab.payload.docId : undefined;
  const payloadSpaceId = typeof tab.payload?.spacePublicId === "string" ? tab.payload.spacePublicId : undefined;
  const incomingContent = typeof tab.payload?.content === "string" ? tab.payload.content : undefined;

  const spacePublicId = payloadSpaceId ?? authSpace?.public_id;
  const isRemoteDoc = Boolean(payloadDocId && spacePublicId);

  const [title, setTitle] = useState("Markdown");
  const [content, setContent] = useState<string>(incomingContent ?? DEFAULT_CONTENT);
  const [mode, setMode] = useState<ViewMode>("split");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [snapshot, setSnapshot] = useState(content);
  const [statusText, setStatusText] = useState<string>(isRemoteDoc ? "Remote" : "Local draft");

  useEffect(() => {
    if (incomingContent !== undefined) {
      setContent(incomingContent);
      setSnapshot(incomingContent);
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
        setContent(doc.markdown_text || "");
        setSnapshot(doc.markdown_text || "");
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

  const dirty = content !== snapshot;

  const stats = useMemo(() => {
    const lines = content ? content.split(/\r\n|\r|\n/).length : 0;
    const chars = content.length;
    return { lines, chars };
  }, [content]);

  const onSave = async () => {
    if (!isRemoteDoc || !payloadDocId || !spacePublicId || saving) {
      return;
    }

    setSaving(true);
    setStatusText("Saving...");
    try {
      const doc = await saveMarkdownDoc(spacePublicId, payloadDocId, {
        title,
        markdown_text: content,
      });
      setTitle(doc.title || title);
      setSnapshot(doc.markdown_text || content);
      setStatusText(`Saved · chunks ${doc.chunk_count}`);
      log(`[Markdown] saved doc ${doc.doc_id} and rebuilt vectors (${doc.chunk_count} chunks)`);
    } catch (err: any) {
      setStatusText("Save failed");
      log(`[Markdown] save failed: ${err?.message ?? String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="col" style={{ minHeight: 0, gap: 8 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="row" style={{ gap: 6, alignItems: "center", flex: 1 }}>
          <input
            className="input"
            style={{ maxWidth: 360, fontSize: 12 }}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Document title"
          />
          <button className={`btn btn-ghost ${mode === "split" ? "active" : ""}`} onClick={() => setMode("split")}>Split</button>
          <button className={`btn btn-ghost ${mode === "edit" ? "active" : ""}`} onClick={() => setMode("edit")}>Edit</button>
          <button className={`btn btn-ghost ${mode === "preview" ? "active" : ""}`} onClick={() => setMode("preview")}>Preview</button>
        </div>

        <div className="row" style={{ gap: 8, alignItems: "center" }}>
          <span className="badge">{stats.lines} lines / {stats.chars} chars</span>
          <span className="badge">{statusText}</span>
          {isRemoteDoc && (
            <button className="btn btn-primary" onClick={onSave} disabled={saving || loading || !dirty}>
              {saving ? "Saving..." : dirty ? "Save" : "Saved"}
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div style={{ color: "var(--text-muted)", padding: 12 }}>Loading markdown...</div>
      ) : (
        <div className={mode === "split" ? "md-split" : "col"} style={{ minHeight: 0, flex: 1 }}>
          {mode !== "preview" && (
            <textarea
              className="md-editor"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Write markdown..."
            />
          )}

          {mode !== "edit" && (
            <div className="md-preview">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || "_(empty markdown document)_"}</ReactMarkdown>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
