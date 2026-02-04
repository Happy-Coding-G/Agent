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
  onUploadFile: (folderId: number, publicId: string) => void;
  onCreateSubFolder: (parentId: number, name: string) => void;
}

function TreeNode({ node, level, expandedIds, onToggleExpand, onUploadFile, onCreateSubFolder }: TreeNodeProps) {
  const hasChildren = node.children && node.children.length > 0;
  const hasFiles = node.files && node.files.length > 0;
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
    if (subFolderName.trim()) {
      onCreateSubFolder(node.id, subFolderName.trim());
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
            {hasChildren || hasFiles ? (isExpanded ? "▼" : "▶") : "•"}
          </span>
          <span className="tree-icon">📁</span>
          <span className="tree-label">{node.name}</span>
          <div className="folder-actions">
            <span
              className="folder-action-btn"
              title="新建子文件夹"
              onClick={(e) => {
                e.stopPropagation();
                setShowSubFolderInput(!showSubFolderInput);
              }}
            >
              ➕
            </span>
            <span
              className="folder-action-btn"
              title="上传文件"
              onClick={(e) => {
                e.stopPropagation();
                onUploadFile(node.id, node.public_id);
              }}
            >
              ⬆️
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
            placeholder="输入子文件夹名称"
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
            <FileNode key={file.public_id} file={file} level={level + 1} indentWidth={indentWidth} />
          ))}
        </div>
      )}
    </div>
  );
}

function FileNode({ file, level, indentWidth }: { file: FileBrief; level: number; indentWidth: number }) {
  const getFileIcon = (mime: string | null) => {
    if (!mime) return "📄";
    if (mime.startsWith("image/")) return "🖼️";
    if (mime.startsWith("video/")) return "🎬";
    if (mime.startsWith("audio/")) return "🎵";
    if (mime.includes("pdf")) return "📕";
    if (mime.includes("word") || mime.includes("document")) return "📘";
    if (mime.includes("excel") || mime.includes("spreadsheet")) return "📗";
    if (mime.includes("powerpoint") || mime.includes("presentation")) return "📙";
    if (mime.includes("zip") || mime.includes("archive") || mime.includes("rar")) return "📦";
    if (mime.includes("text/")) return "📝";
    return "📄";
  };

  const formatSize = (bytes: number | null) => {
    if (!bytes) return "-";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };

  return (
    <div
      className="tree-content file-node"
      style={{ paddingLeft: 24 }}
    >
      <span className="tree-icon">{getFileIcon(file.mime)}</span>
      <span className="tree-label">{file.name}</span>
      <span style={{ fontSize: "11px", color: "var(--text-muted)", marginLeft: "auto" }}>
        {formatSize(file.size_bytes)}
      </span>
    </div>
  );
}

export default function ExplorerView() {
  const space = useAuth(s => s.currentSpace);
  const spaceRefreshKey = useWorkbench(s => s.spaceRefreshKey);
  const openTab = useWorkbench(s => s.openTab);
  const log = useWorkbench(s => s.log);
  const [tree, setTree] = useState<TreeFolder[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [showRootFolderInput, setShowRootFolderInput] = useState(false);
  const [rootFolderName, setRootFolderName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (showRootFolderInput && inputRef.current) {
      inputRef.current.focus();
    }
  }, [showRootFolderInput]);

  const loadTree = useCallback(async (keepExpanded = false) => {
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
      log(`[Explorer] 获取目录树失败: ${String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [space?.public_id, log]);

  useEffect(() => {
    loadTree();
  }, [loadTree, spaceRefreshKey]);

  const onToggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const onUploadFile = useCallback((folderId: number, publicId: string) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = false;
    input.onchange = async () => {
      const files = input.files;
      if (!files || !files[0]) return;
      const file = files[0];
      
      if (!space?.public_id) {
        log("[Explorer] 请先选择空间");
        return;
      }
      
      try {
        log(`[Explorer] 开始上传文件: ${file.name}`);
        await uploadFile(space.public_id, folderId, file);
        log(`[Explorer] 上传文件成功: ${file.name}`);
        setExpandedIds(prev => new Set(prev).add(publicId));
        loadTree(true);
      } catch (e: any) {
        log(`[Explorer] 上传文件失败: ${file.name} - ${e?.message ?? String(e)}`);
      }
    };
    input.click();
  }, [space?.public_id, log, loadTree]);

  const onCreateSubFolder = useCallback(async (parentId: number, name: string) => {
    if (!space?.public_id) return;
    try {
      await createFolder(space.public_id, { name, parent_id: parentId });
      log(`[Explorer] 创建子文件夹成功: ${name}`);
      loadTree();
    } catch (e: any) {
      log(`[Explorer] 创建文件夹失败: ${String(e)}`);
    }
  }, [space?.public_id, log, loadTree]);

  const onCreateRootFolder = useCallback(async () => {
    if (!space?.public_id || !rootFolderName.trim()) return;
    try {
      await createFolder(space.public_id, { name: rootFolderName.trim(), parent_id: null });
      log(`[Explorer] 创建根文件夹成功: ${rootFolderName}`);
      setShowRootFolderInput(false);
      setRootFolderName("");
      loadTree();
    } catch (e: any) {
      log(`[Explorer] 创建文件夹失败: ${String(e)}`);
    }
  }, [space?.id, rootFolderName, log, loadTree]);

  const refresh = useCallback(() => {
    loadTree();
  }, [loadTree]);

  const collapseAll = useCallback(() => {
    setExpandedIds(new Set());
  }, []);

  return (
    <div className="col" style={{ gap: "12px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 4px" }}>
        <span style={{ fontSize: "11px", textTransform: "uppercase", color: "var(--text-muted)", letterSpacing: "0.5px", fontWeight: 600 }}>
          Folders
        </span>
        <div style={{ display: "flex", gap: "4px" }}>
          {tree.length > 0 && (
            <button
              className="folder-action-btn"
              title="新建根文件夹"
              onClick={() => setShowRootFolderInput(true)}
            >
              ➕
            </button>
          )}
          <button className="folder-action-btn" onClick={refresh} title="刷新">🔄</button>
          <button className="folder-action-btn" onClick={collapseAll} title="全部折叠">⊟</button>
        </div>
      </div>

      {showRootFolderInput && tree.length > 0 && (
        <div style={{ padding: "0 4px" }}>
          <input
            ref={inputRef}
            type="text"
            className="input"
            placeholder="输入根文件夹名称"
            value={rootFolderName}
            onChange={(e) => setRootFolderName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onCreateRootFolder();
              if (e.key === "Escape") {
                setShowRootFolderInput(false);
                setRootFolderName("");
              }
            }}
            onClick={(e) => e.stopPropagation()}
            style={{ width: "100%", fontSize: 12, padding: "6px 8px" }}
          />
        </div>
      )}

      {loading && (
        <div style={{ color: "var(--text-muted)", padding: "8px" }}>
          <span className="spinner" style={{ width: 14, height: 14, marginRight: 8 }} />
          加载中...
        </div>
      )}

      {!loading && tree.length === 0 && (
        <div className="empty-state" style={{ padding: "40px 20px" }}>
          <div className="empty-state-icon" style={{ fontSize: 40 }}>📂</div>
          <div className="empty-state-title" style={{ fontSize: 15 }}>暂无文件夹</div>
          <div className="empty-state-description" style={{ fontSize: 13, marginBottom: 16, color: "var(--text-muted)" }}>
            {space ? `空间 "${space.name}" 中还没有文件` : "请先选择一个空间"}
          </div>
          {space && (
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", justifyContent: "center" }}>
              {showRootFolderInput ? (
                <input
                  ref={inputRef}
                  type="text"
                  className="input"
                  placeholder="输入文件夹名称"
                  value={rootFolderName}
                  onChange={(e) => setRootFolderName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onCreateRootFolder();
                    if (e.key === "Escape") {
                      setShowRootFolderInput(false);
                      setRootFolderName("");
                    }
                  }}
                  onClick={(e) => e.stopPropagation()}
                  style={{ width: 150, fontSize: 12, padding: "6px 8px" }}
                />
              ) : (
                <button className="quick-action-btn" onClick={() => setShowRootFolderInput(true)}>
                  📁 新建文件夹
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {!loading && tree.length > 0 && tree.map(node => (
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

      {tree.length > 0 && (
        <div style={{ marginTop: "8px", padding: "8px", background: "var(--panel-2)", borderRadius: "var(--radius)", fontSize: "11px", color: "var(--text-muted)" }}>
          💡 提示：➕ 新建文件夹，⬆️ 上传文件
        </div>
      )}
    </div>
  );
}