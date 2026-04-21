import { useEffect, useState, useCallback, useRef } from "react";
import { getSpaceTree, createFolder, uploadFile } from "../api/ptds";
import { TreeFolder, FileBrief } from "../types";
import { useWorkbench } from "../store/workbench";
import { useAuth } from "../store/auth";

interface TreeNodeProps {
  node: TreeFolder;
  level: number;
  expandedIds: Set<string>;
  onToggleExpand: (id: string) => void;
  onUploadFile: (folderPublicId: string, publicId: string) => void;
  onCreateSubFolder: (parentId: number, name: string) => void;
}

function TreeNode({ node, level, expandedIds, onToggleExpand, onUploadFile, onCreateSubFolder }: TreeNodeProps) {
  const hasChildren = node.children.length > 0;
  const hasFiles = node.files.length > 0;
  const isExpanded = expandedIds.has(node.public_id);
  const [showSubFolderInput, setShowSubFolderInput] = useState(false);
  const [subFolderName, setSubFolderName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (showSubFolderInput && inputRef.current) {
      inputRef.current.focus();
    }
  }, [showSubFolderInput]);

  const handleSubFolderSubmit = () => {
    const name = subFolderName.trim();
    if (name) {
      onCreateSubFolder(node.id, name);
    }
    setShowSubFolderInput(false);
    setSubFolderName("");
  };

  const indentWidth = 20;

  return (
    <div className="tree-node">
      <div className="tree-row-wrapper" style={{ paddingLeft: level * indentWidth }}>
        <div className="tree-content">
          <span
            className={`tree-expand-icon ${isExpanded ? "expanded" : ""}`}
            onClick={(e) => {
              e.stopPropagation();
              if (hasChildren || hasFiles) onToggleExpand(node.public_id);
            }}
          >
            {hasChildren || hasFiles ? (isExpanded ? "v" : ">") : "-"}
          </span>
          <span className="tree-icon">[DIR]</span>
          <span className="tree-label">{node.name}</span>
          <div className="folder-actions">
            <span
              className="folder-action-btn"
              title="Create sub folder"
              onClick={(e) => {
                e.stopPropagation();
                setShowSubFolderInput((prev) => !prev);
              }}
            >
              +
            </span>
            <span
              className="folder-action-btn"
              title="Upload file"
              onClick={(e) => {
                e.stopPropagation();
                onUploadFile(node.public_id, node.public_id);
              }}
            >
              UP
            </span>
          </div>
        </div>
      </div>

      {showSubFolderInput && (
        <div style={{ paddingLeft: (level + 1) * indentWidth + 24 }}>
          <input
            ref={inputRef}
            type="text"
            className="input"
            placeholder="Sub folder name"
            value={subFolderName}
            onChange={(e) => setSubFolderName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubFolderSubmit();
              if (e.key === "Escape") {
                setShowSubFolderInput(false);
                setSubFolderName("");
              }
            }}
            onClick={(e) => e.stopPropagation()}
            style={{ width: "100%", fontSize: 12, padding: "6px 8px" }}
          />
        </div>
      )}

      {isExpanded && hasChildren && (
        <div className="tree-node-children">
          {node.children.map((child) => (
            <TreeNode
              key={child.public_id}
              node={child}
              level={level + 1}
              expandedIds={expandedIds}
              onToggleExpand={onToggleExpand}
              onUploadFile={onUploadFile}
              onCreateSubFolder={onCreateSubFolder}
            />
          ))}
        </div>
      )}

      {isExpanded && hasFiles && (
        <div className="tree-files" style={{ paddingLeft: (level + 1) * indentWidth + 24 }}>
          {node.files.map((file) => (
            <FileNode key={file.public_id} file={file} />
          ))}
        </div>
      )}
    </div>
  );
}

function FileNode({ file }: { file: FileBrief }) {
  return (
    <div className="tree-content file-node" style={{ paddingLeft: 24 }}>
      <span className="tree-icon">[FILE]</span>
      <span className="tree-label">{file.name}</span>
      <span style={{ fontSize: "11px", color: "var(--text-muted)", marginLeft: "auto" }}>
        {formatSize(file.size_bytes)}
      </span>
    </div>
  );
}

export default function ExplorerView() {
  const space = useAuth((s) => s.currentSpace);
  const spaceRefreshKey = useWorkbench((s) => s.spaceRefreshKey);
  const log = useWorkbench((s) => s.log);
  const [tree, setTree] = useState<TreeFolder[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [showRootFolderInput, setShowRootFolderInput] = useState(false);
  const [rootFolderName, setRootFolderName] = useState("");
  const [creatingRootFolder, setCreatingRootFolder] = useState(false);
  const [rootFolderError, setRootFolderError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (showRootFolderInput && inputRef.current) {
      inputRef.current.focus();
    }
  }, [showRootFolderInput]);

  const loadTree = useCallback(
    async (keepExpanded = false) => {
      if (!space?.public_id) {
        setTree([]);
        return;
      }
      setLoading(true);
      try {
        const data = await getSpaceTree(space.public_id);
        if (!keepExpanded) {
          setExpandedIds(new Set());
        }
        setTree(data);
      } catch (e: any) {
        log(`[Explorer] failed to load tree: ${e?.message ?? String(e)}`);
      } finally {
        setLoading(false);
      }
    },
    [space?.public_id, log],
  );

  useEffect(() => {
    void loadTree();
  }, [loadTree, spaceRefreshKey]);

  const onToggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const onUploadFile = useCallback(
    (folderPublicId: string, publicId: string) => {
      const input = document.createElement("input");
      input.type = "file";
      input.multiple = false;
      input.onchange = async () => {
        const files = input.files;
        if (!files || !files[0]) return;
        const file = files[0];

        if (!space?.public_id) {
          log("[Explorer] select a space first");
          return;
        }

        try {
          log(`[Explorer] uploading: ${file.name}`);
          await uploadFile(space.public_id, folderPublicId, file);
          log(`[Explorer] upload succeeded: ${file.name}`);
          setExpandedIds((prev) => new Set(prev).add(publicId));
          void loadTree(true);
        } catch (e: any) {
          log(`[Explorer] upload failed: ${file.name} - ${e?.message ?? String(e)}`);
        }
      };
      input.click();
    },
    [space?.public_id, log, loadTree],
  );

  const onCreateSubFolder = useCallback(
    async (parentId: number, name: string) => {
      if (!space?.public_id) return;
      try {
        await createFolder(space.public_id, { name, parent_id: parentId });
        log(`[Explorer] sub folder created: ${name}`);
        void loadTree();
      } catch (e: any) {
        log(`[Explorer] create folder failed: ${e?.message ?? String(e)}`);
      }
    },
    [space?.public_id, log, loadTree],
  );

  const onCreateRootFolder = useCallback(async () => {
    if (!space?.public_id) return;
    const name = rootFolderName.trim();
    if (!name) {
      setRootFolderError("Folder name is required");
      return;
    }
    setCreatingRootFolder(true);
    setRootFolderError(null);
    try {
      await createFolder(space.public_id, { name, parent_id: null });
      log(`[Explorer] root folder created: ${name}`);
      setShowRootFolderInput(false);
      setRootFolderName("");
      setRootFolderError(null);
      void loadTree();
    } catch (e: any) {
      const message = e?.message ?? String(e);
      log(`[Explorer] create folder failed: ${message}`);
      setRootFolderError(message);
    } finally {
      setCreatingRootFolder(false);
    }
  }, [space?.public_id, rootFolderName, log, loadTree]);

  const openCreateRootFolder = useCallback(() => {
    setShowRootFolderInput(true);
    setRootFolderError(null);
  }, []);

  const cancelCreateRootFolder = useCallback(() => {
    setShowRootFolderInput(false);
    setRootFolderName("");
    setRootFolderError(null);
  }, []);

  return (
    <div className="col" style={{ gap: "12px", padding: "12px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingBottom: "12px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <span style={{ fontSize: "12px", textTransform: "uppercase", color: "#94A3B8", letterSpacing: "1px", fontWeight: 600 }}>
          文件夹
        </span>
        <div style={{ display: "flex", gap: "6px" }}>
          {space && (
            <button className="folder-action-btn" title="Create root folder" onClick={openCreateRootFolder} style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, borderRadius: 4, border: "none", background: "rgba(255,255,255,0.05)", color: "#E2E8F0", cursor: "pointer", transition: "all 0.2s" }}>
              +
            </button>
          )}
          <button className="folder-action-btn" onClick={() => void loadTree()} title="Refresh" style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, borderRadius: 4, border: "none", background: "rgba(255,255,255,0.05)", color: "#E2E8F0", cursor: "pointer", transition: "all 0.2s" }}>⟳</button>
          <button className="folder-action-btn" onClick={() => setExpandedIds(new Set())} title="Collapse all" style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, borderRadius: 4, border: "none", background: "rgba(255,255,255,0.05)", color: "#E2E8F0", cursor: "pointer", transition: "all 0.2s" }}>-</button>
        </div>
      </div>

      {showRootFolderInput && space && (
        <div style={{ padding: "12px", background: "rgba(255,255,255,0.03)", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 10 }}>
          <input
            ref={inputRef}
            type="text"
            onChange={(e) => setRootFolderName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void onCreateRootFolder();
              if (e.key === "Escape") {
                cancelCreateRootFolder();
              }
            }}
            placeholder="新文件夹名称..."
            style={{ width: "100%", fontSize: 13, padding: "8px 12px", background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, color: "#E2E8F0", outline: "none" }}
          />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button
              onClick={cancelCreateRootFolder}
              disabled={creatingRootFolder}
              style={{ padding: "6px 12px", fontSize: 12, background: "transparent", color: "#94A3B8", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, cursor: "pointer" }}
            >
              取消
            </button>
            <button
              onClick={() => void onCreateRootFolder()}
              disabled={creatingRootFolder || !rootFolderName.trim()}
              style={{ padding: "6px 12px", fontSize: 12, background: "#3B82F6", color: "white", border: "none", borderRadius: 4, cursor: "pointer", opacity: creatingRootFolder || !rootFolderName.trim() ? 0.5 : 1 }}
            >
              {creatingRootFolder ? "创建中..." : "创建"}
            </button>
          </div>
          {rootFolderError && (
            <div style={{ color: "#EF4444", fontSize: 12, marginTop: 4 }}>
              {rootFolderError}
            </div>
          )}
        </div>
      )}

      {loading && <div style={{ color: "var(--text-muted)", padding: "8px" }}>Loading...</div>}

      {!loading && tree.length === 0 && (
        <div className="empty-state" style={{ padding: "60px 20px", textAlign: "center", background: "rgba(255,255,255,0.02)", borderRadius: 12, border: "1px dashed rgba(255,255,255,0.05)" }}>
          <div style={{ fontSize: 40, opacity: 0.5, marginBottom: 16 }}>📁</div>
          <div style={{ fontSize: 15, fontWeight: 500, color: "#E2E8F0", marginBottom: 8 }}>暂无文件夹</div>
          <div style={{ fontSize: 13, marginBottom: 24, color: "#94A3B8" }}>
            {space ? `空间 "${space.name}" 目前是空的` : "请先选择一个工作空间"}
          </div>
          {space && (
            <button onClick={openCreateRootFolder} style={{ padding: "8px 16px", borderRadius: 6, background: "#3B82F6", color: "white", border: "none", cursor: "pointer", fontWeight: 500, transition: "background 0.2s" }}>
              创建文件夹
            </button>
          )}
        </div>
      )}

      {!loading && tree.length > 0 &&
        tree.map((node) => (
          <TreeNode
            key={node.public_id}
            node={node}
            level={0}
            expandedIds={expandedIds}
            onToggleExpand={onToggleExpand}
            onUploadFile={onUploadFile}
            onCreateSubFolder={onCreateSubFolder}
          />
        ))}
    </div>
  );
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
