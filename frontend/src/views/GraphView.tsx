import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createGraphEdge,
  deleteGraphEdge,
  getKnowledgeGraph,
  updateGraphEdge,
  updateGraphNode,
} from "../api/ptds";
import { useAuth } from "../store/auth";
import { useWorkbench } from "../store/workbench";
import { GraphEdge, GraphNode } from "../types";

type PositionedNode = GraphNode & {
  degree: number;
  x: number;
  y: number;
};

type PositionedEdge = GraphEdge & {
  source: PositionedNode | null;
  target: PositionedNode | null;
  laneOffset: number;
};

export type GraphViewMode = "full" | "display" | "editor";

type GraphViewProps = {
  mode?: GraphViewMode;
  showToolbar?: boolean;
  canvasHeight?: number;
};

const GRAPH_WIDTH = 980;
const GRAPH_HEIGHT = 560;
const NODE_RADIUS = 22;
const NODE_RADIUS_SELECTED = 28;

function hashString(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i += 1) {
    hash = (hash * 31 + input.charCodeAt(i)) >>> 0;
  }
  return hash;
}

function pairKey(sourceDocId: string, targetDocId: string): string {
  if (sourceDocId <= targetDocId) {
    return `${sourceDocId}::${targetDocId}`;
  }
  return `${targetDocId}::${sourceDocId}`;
}

function shorten(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 1))}...`;
}

function buildGraphLayout(nodes: GraphNode[], edges: GraphEdge[]): { nodes: PositionedNode[]; edges: PositionedEdge[] } {
  if (nodes.length === 0) {
    return { nodes: [], edges: [] };
  }

  const degreeMap = new Map<string, number>();
  for (const node of nodes) {
    degreeMap.set(node.doc_id, 0);
  }
  for (const edge of edges) {
    degreeMap.set(edge.source_doc_id, (degreeMap.get(edge.source_doc_id) ?? 0) + 1);
    degreeMap.set(edge.target_doc_id, (degreeMap.get(edge.target_doc_id) ?? 0) + 1);
  }

  const sorted = [...nodes].sort((a, b) => {
    const degreeDiff = (degreeMap.get(b.doc_id) ?? 0) - (degreeMap.get(a.doc_id) ?? 0);
    if (degreeDiff !== 0) return degreeDiff;
    return a.label.localeCompare(b.label);
  });

  const capacities = [1, 8, 14, 20, 26];
  const radii = [0, 130, 220, 310, 400];
  while (capacities.reduce((sum, value) => sum + value, 0) < sorted.length) {
    const lastCap = capacities[capacities.length - 1];
    const lastRadius = radii[radii.length - 1];
    capacities.push(lastCap + 6);
    radii.push(lastRadius + 95);
  }

  const centerX = GRAPH_WIDTH / 2;
  const centerY = GRAPH_HEIGHT / 2;
  const layoutMap = new Map<string, { x: number; y: number }>();

  let assigned = 0;
  for (let ringIndex = 0; ringIndex < capacities.length && assigned < sorted.length; ringIndex += 1) {
    const ringCapacity = capacities[ringIndex];
    const ringRadius = radii[ringIndex];
    const take = Math.min(ringCapacity, sorted.length - assigned);

    for (let offset = 0; offset < take; offset += 1) {
      const node = sorted[assigned + offset];
      if (!node) continue;

      if (ringIndex === 0) {
        layoutMap.set(node.doc_id, { x: centerX, y: centerY });
        continue;
      }

      const baseAngle = (-Math.PI / 2) + (2 * Math.PI * offset) / take;
      const jitter = ((hashString(node.doc_id) % 100) / 100 - 0.5) * 0.14;
      const angle = baseAngle + jitter;

      layoutMap.set(node.doc_id, {
        x: centerX + Math.cos(angle) * ringRadius,
        y: centerY + Math.sin(angle) * ringRadius,
      });
    }

    assigned += take;
  }

  const positionedNodes: PositionedNode[] = nodes.map((node) => {
    const fallback = { x: centerX, y: centerY };
    const point = layoutMap.get(node.doc_id) ?? fallback;
    return {
      ...node,
      degree: degreeMap.get(node.doc_id) ?? 0,
      x: point.x,
      y: point.y,
    };
  });

  const nodeById = new Map<string, PositionedNode>();
  for (const node of positionedNodes) {
    nodeById.set(node.doc_id, node);
  }

  const pairCounts = new Map<string, number>();
  for (const edge of edges) {
    const key = pairKey(edge.source_doc_id, edge.target_doc_id);
    pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
  }

  const pairSeen = new Map<string, number>();
  const positionedEdges: PositionedEdge[] = edges.map((edge) => {
    const key = pairKey(edge.source_doc_id, edge.target_doc_id);
    const seen = pairSeen.get(key) ?? 0;
    pairSeen.set(key, seen + 1);
    const total = pairCounts.get(key) ?? 1;
    const laneOffset = (seen - (total - 1) / 2) * 14;

    return {
      ...edge,
      source: nodeById.get(edge.source_doc_id) ?? null,
      target: nodeById.get(edge.target_doc_id) ?? null,
      laneOffset,
    };
  });

  return {
    nodes: positionedNodes,
    edges: positionedEdges,
  };
}

export default function GraphView({
  mode = "full",
  showToolbar = true,
  canvasHeight = 340,
}: GraphViewProps) {
  const space = useAuth((s) => s.currentSpace);
  const log = useWorkbench((s) => s.log);

  const [loading, setLoading] = useState(false);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string>("");
  const [nodeLabel, setNodeLabel] = useState("");
  const [nodeDescription, setNodeDescription] = useState("");
  const [nodeTags, setNodeTags] = useState("");
  const [edgeSource, setEdgeSource] = useState("");
  const [edgeTarget, setEdgeTarget] = useState("");
  const [edgeType, setEdgeType] = useState("related_to");
  const [edgeDesc, setEdgeDesc] = useState("");

  const selectedNode = useMemo(
    () => nodes.find((n) => n.doc_id === selectedDocId) || null,
    [nodes, selectedDocId],
  );
  const showDisplay = mode !== "editor";
  const showEditor = mode !== "display";

  const visual = useMemo(() => buildGraphLayout(nodes, edges), [nodes, edges]);

  const loadGraph = useCallback(async () => {
    if (!space?.public_id) {
      setNodes([]);
      setEdges([]);
      setSelectedDocId("");
      return;
    }

    setLoading(true);
    try {
      const graph = await getKnowledgeGraph(space.public_id);
      const nextNodes = graph.nodes || [];
      const nextEdges = graph.edges || [];
      setNodes(nextNodes);
      setEdges(nextEdges);
      setSelectedDocId((prev) => {
        if (prev && nextNodes.some((node) => node.doc_id === prev)) {
          return prev;
        }
        return nextNodes[0]?.doc_id ?? "";
      });
    } catch (e: any) {
      log(`[Graph] load failed: ${e?.message ?? String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [space?.public_id, log]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  useEffect(() => {
    if (!selectedNode) {
      setNodeLabel("");
      setNodeDescription("");
      setNodeTags("");
      return;
    }
    setNodeLabel(selectedNode.label || "");
    setNodeDescription(selectedNode.description || "");
    setNodeTags((selectedNode.tags || []).join(", "));
  }, [selectedNode]);

  const onSaveNode = async () => {
    if (!space?.public_id || !selectedNode) return;

    try {
      const updated = await updateGraphNode(space.public_id, selectedNode.doc_id, {
        label: nodeLabel,
        description: nodeDescription,
        tags: nodeTags
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
      });
      setNodes((prev) => prev.map((n) => (n.doc_id === updated.doc_id ? { ...n, ...updated } : n)));
      log(`[Graph] node updated: ${updated.doc_id}`);
    } catch (e: any) {
      log(`[Graph] node update failed: ${e?.message ?? String(e)}`);
    }
  };

  const onCreateEdge = async () => {
    if (!space?.public_id || !edgeSource || !edgeTarget) return;
    try {
      const created = await createGraphEdge(space.public_id, {
        source_doc_id: edgeSource,
        target_doc_id: edgeTarget,
        relation_type: edgeType,
        description: edgeDesc,
      });
      setEdges((prev) => [created, ...prev]);
      setEdgeDesc("");
      log(`[Graph] edge created: ${created.edge_id}`);
    } catch (e: any) {
      log(`[Graph] edge create failed: ${e?.message ?? String(e)}`);
    }
  };

  const onUpdateEdge = async (edge: GraphEdge) => {
    if (!space?.public_id) return;
    try {
      const updated = await updateGraphEdge(space.public_id, edge.edge_id, {
        relation_type: edge.relation_type,
        description: edge.description,
      });
      setEdges((prev) => prev.map((item) => (item.edge_id === updated.edge_id ? updated : item)));
      log(`[Graph] edge updated: ${updated.edge_id}`);
    } catch (e: any) {
      log(`[Graph] edge update failed: ${e?.message ?? String(e)}`);
    }
  };

  const onDeleteEdge = async (edgeId: string) => {
    if (!space?.public_id) return;
    try {
      await deleteGraphEdge(space.public_id, edgeId);
      setEdges((prev) => prev.filter((item) => item.edge_id !== edgeId));
      log(`[Graph] edge deleted: ${edgeId}`);
    } catch (e: any) {
      log(`[Graph] edge delete failed: ${e?.message ?? String(e)}`);
    }
  };

  return (
    <div className="col" style={{ gap: 16, minHeight: 0, padding: "16px" }}>
      {showToolbar && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingBottom: "12px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
          <h3 style={{ margin: 0, fontSize: "14px", fontWeight: 600, color: "#E2E8F0", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: "16px" }}>🕸️</span> 知识图谱
          </h3>
          <button 
            style={{ padding: "4px 8px", fontSize: 12, background: "transparent", color: "#94A3B8", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, cursor: "pointer", transition: "all 0.2s" }} 
            onClick={() => void loadGraph()} 
            disabled={loading}
            onMouseEnter={(e) => Object.assign(e.currentTarget.style, { background: "rgba(255,255,255,0.05)", color: "#E2E8F0" })}
            onMouseLeave={(e) => Object.assign(e.currentTarget.style, { background: "transparent", color: "#94A3B8" })}
          >
            {loading ? "↻" : "⟳ 刷新"}
          </button>
        </div>
      )}

      {!space && (
        <div style={{ padding: "40px 20px", textAlign: "center", background: "rgba(255,255,255,0.02)", borderRadius: 12, border: "1px dashed rgba(255,255,255,0.05)" }}>
          <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.5 }}>🌐</div>
          <div style={{ color: "#94A3B8", fontSize: 13 }}>请先选择一个 Space</div>
        </div>
      )}

      {space && (
        <>
          {showDisplay && (
            <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span>📈</span> 图谱预览</span>
                <span style={{ color: "#94A3B8", fontSize: 12, fontWeight: 400 }}>{nodes.length} 节点 / {edges.length} 边</span>
              </div>

              {nodes.length === 0 ? (
                <div style={{ padding: "30px 20px", textAlign: "center", background: "rgba(0,0,0,0.2)", borderRadius: 8, border: "1px dashed rgba(255,255,255,0.05)" }}>
                  <div style={{ color: "#64748B", fontSize: 13 }}>图谱暂无数据</div>
                </div>
              ) : (
              <div style={{ border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden", background: "#151515" }}>
                <svg
                  viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`}
                  style={{ width: "100%", height: canvasHeight, display: "block" }}
                >
                  <defs>
                    <marker
                      id="kg-arrow"
                      viewBox="0 0 10 10"
                      refX="8"
                      refY="5"
                      markerWidth="8"
                      markerHeight="8"
                      orient="auto-start-reverse"
                    >
                      <path d="M 0 0 L 10 5 L 0 10 z" fill="#8b8f97" />
                    </marker>
                  </defs>

                  <rect x={0} y={0} width={GRAPH_WIDTH} height={GRAPH_HEIGHT} fill="#151515" />

                  {visual.edges.map((edge) => {
                    if (!edge.source || !edge.target) {
                      return null;
                    }

                    const isSelfLoop = edge.source.doc_id === edge.target.doc_id;
                    const isSelected = selectedDocId !== "" && (
                      edge.source.doc_id === selectedDocId || edge.target.doc_id === selectedDocId
                    );

                    if (isSelfLoop) {
                      const x = edge.source.x;
                      const y = edge.source.y;
                      const loopSize = 34 + Math.abs(edge.laneOffset);
                      const loopPath = `M ${x} ${y - NODE_RADIUS} C ${x + loopSize} ${y - loopSize} ${x + loopSize} ${y + loopSize} ${x} ${y + NODE_RADIUS}`;

                      return (
                        <g key={edge.edge_id}>
                          <path
                            d={loopPath}
                            fill="none"
                            stroke={isSelected ? "#9aa7ff" : "#8b8f97"}
                            strokeWidth={isSelected ? 2.2 : 1.4}
                            markerEnd="url(#kg-arrow)"
                            opacity={0.9}
                          />
                          <text
                            x={x + loopSize + 10}
                            y={y}
                            fill={isSelected ? "#cdd4ff" : "#a7abb3"}
                            fontSize="11"
                            textAnchor="start"
                            dominantBaseline="middle"
                          >
                            {shorten(edge.relation_type, 18)}
                          </text>
                        </g>
                      );
                    }

                    const dx = edge.target.x - edge.source.x;
                    const dy = edge.target.y - edge.source.y;
                    const length = Math.max(Math.hypot(dx, dy), 1);
                    const nx = -dy / length;
                    const ny = dx / length;
                    const laneX = nx * edge.laneOffset;
                    const laneY = ny * edge.laneOffset;

                    const sourceRadius = edge.source.doc_id === selectedDocId ? NODE_RADIUS_SELECTED : NODE_RADIUS;
                    const targetRadius = edge.target.doc_id === selectedDocId ? NODE_RADIUS_SELECTED : NODE_RADIUS;

                    const startX = edge.source.x + (dx / length) * sourceRadius + laneX;
                    const startY = edge.source.y + (dy / length) * sourceRadius + laneY;
                    const endX = edge.target.x - (dx / length) * (targetRadius + 10) + laneX;
                    const endY = edge.target.y - (dy / length) * (targetRadius + 10) + laneY;

                    const midX = (startX + endX) / 2 + nx * 6;
                    const midY = (startY + endY) / 2 + ny * 6;

                    return (
                      <g key={edge.edge_id}>
                        <line
                          x1={startX}
                          y1={startY}
                          x2={endX}
                          y2={endY}
                          stroke={isSelected ? "#9aa7ff" : "#8b8f97"}
                          strokeWidth={isSelected ? 2.1 : 1.2}
                          markerEnd="url(#kg-arrow)"
                          opacity={0.92}
                        />
                        <text
                          x={midX}
                          y={midY}
                          fill={isSelected ? "#d0d7ff" : "#9fa4ad"}
                          fontSize="10"
                          textAnchor="middle"
                          dominantBaseline="middle"
                          style={{ pointerEvents: "none" }}
                        >
                          {shorten(edge.relation_type, 16)}
                        </text>
                      </g>
                    );
                  })}

                  {visual.nodes.map((node) => {
                    const isSelected = node.doc_id === selectedDocId;
                    const radius = isSelected ? NODE_RADIUS_SELECTED : NODE_RADIUS;

                    return (
                      <g
                        key={node.doc_id}
                        transform={`translate(${node.x}, ${node.y})`}
                        onClick={() => setSelectedDocId(node.doc_id)}
                        style={{ cursor: "pointer" }}
                      >
                        <circle
                          r={radius}
                          fill={isSelected ? "#4f46e5" : "#2b2f36"}
                          stroke={isSelected ? "#b7b0ff" : "#6f7480"}
                          strokeWidth={isSelected ? 2.4 : 1.3}
                        />
                        <text
                          x={0}
                          y={-2}
                          fill={isSelected ? "#fff" : "#d9dbe1"}
                          fontSize="11"
                          textAnchor="middle"
                          dominantBaseline="middle"
                          style={{ pointerEvents: "none", fontWeight: 600 }}
                        >
                          {shorten(node.label || "(untitled)", 12)}
                        </text>
                        <text
                          x={0}
                          y={12}
                          fill={isSelected ? "#e8e5ff" : "#9da3ae"}
                          fontSize="9"
                          textAnchor="middle"
                          dominantBaseline="middle"
                          style={{ pointerEvents: "none" }}
                        >
                          d:{node.degree}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              </div>
            )}

              <div style={{ fontSize: 11, color: "#64748B", marginTop: 12, textAlign: "center" }}>
                {mode === "display"
                  ? "点击节点进行聚焦，使用左侧栏图谱编辑器修改"
                  : "点击节点进行选择和编辑"}
              </div>
            </div>
          )}

          {showEditor && mode === "editor" && (
            <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", display: "flex", alignItems: "center", gap: 6 }}>
                <span>🎯</span> 节点选择器
              </div>
              <select
                value={selectedDocId}
                onChange={(e) => setSelectedDocId(e.target.value)}
                style={{ padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", width: "100%" }}
              >
                <option value="">选择一个节点...</option>
                {nodes.map((node) => (
                  <option key={`node-${node.doc_id}`} value={node.doc_id}>
                    {node.label || node.doc_id}
                  </option>
                ))}
              </select>
            </div>
          )}

          {showEditor && (
            <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <span>📝</span> 编辑选中节点
              </div>
              {selectedNode ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <input 
                    value={nodeLabel} 
                    onChange={(e) => setNodeLabel(e.target.value)} 
                    placeholder="标签 (Label)" 
                    style={{ padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none" }}
                  />
                  <textarea
                    value={nodeDescription}
                    onChange={(e) => setNodeDescription(e.target.value)}
                    placeholder="描述 (Description)"
                    style={{ minHeight: 80, resize: "vertical", padding: "10px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", lineHeight: 1.5 }}
                  />
                  <input 
                    value={nodeTags} 
                    onChange={(e) => setNodeTags(e.target.value)} 
                    placeholder="标签，逗号分隔 (Tags)" 
                    style={{ padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none" }}
                  />
                  <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
                    <button 
                      style={{ padding: "8px 16px", fontSize: 13, background: "#3B82F6", color: "white", border: "none", borderRadius: 6, cursor: "pointer", fontWeight: 500 }} 
                      onClick={() => void onSaveNode()}
                    >
                      保存节点
                    </button>
                  </div>
                </div>
              ) : (
                <div style={{ color: "#64748B", fontSize: 13, textAlign: "center", padding: "16px 0", background: "rgba(0,0,0,0.2)", borderRadius: 8, border: "1px dashed rgba(255,255,255,0.05)" }}>
                  {mode === "editor" ? "请先从选择器中选中一个节点。" : "请先在上方图谱中点击一个节点。"}
                </div>
              )}
            </div>
          )}

          {showEditor && (
            <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <span>🔗</span> 创建关联边
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <select 
                  value={edgeSource} 
                  onChange={(e) => setEdgeSource(e.target.value)} 
                  style={{ padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", width: "100%" }}
                >
                  <option value="">起始节点...</option>
                  {nodes.map((n) => (
                    <option key={`src-${n.doc_id}`} value={n.doc_id}>{n.label}</option>
                  ))}
                </select>
                <select 
                  value={edgeTarget} 
                  onChange={(e) => setEdgeTarget(e.target.value)} 
                  style={{ padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", width: "100%" }}
                >
                  <option value="">目标节点...</option>
                  {nodes.map((n) => (
                    <option key={`tgt-${n.doc_id}`} value={n.doc_id}>{n.label}</option>
                  ))}
                </select>
                <input 
                  value={edgeType} 
                  onChange={(e) => setEdgeType(e.target.value)} 
                  placeholder="关联类型" 
                  style={{ padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", boxSizing: "border-box" }}
                />
                <input 
                  value={edgeDesc} 
                  onChange={(e) => setEdgeDesc(e.target.value)} 
                  placeholder="关联描述" 
                  style={{ padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", boxSizing: "border-box" }}
                />
                <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
                  <button 
                    style={{ padding: "8px 16px", fontSize: 13, background: "transparent", color: "#10B981", border: "1px solid rgba(16,185,129,0.3)", borderRadius: 6, cursor: "pointer", transition: "all 0.2s" }} 
                    onClick={() => void onCreateEdge()}
                    onMouseEnter={(e) => Object.assign(e.currentTarget.style, { background: "rgba(16,185,129,0.1)" })}
                    onMouseLeave={(e) => Object.assign(e.currentTarget.style, { background: "transparent" })}
                  >
                    + 添加边
                  </button>
                </div>
              </div>
            </div>
          )}

          {showEditor && (
            <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", minHeight: 0, display: "flex", flexDirection: "column" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
                <span>🧬</span> 边列表 ({edges.length})
              </div>
              <div style={{ maxHeight: 350, overflow: "auto", display: "grid", gap: 10, paddingRight: 4 }}>
                {edges.map((edge) => {
                  const source = nodes.find((n) => n.doc_id === edge.source_doc_id)?.label || edge.source_doc_id;
                  const target = nodes.find((n) => n.doc_id === edge.target_doc_id)?.label || edge.target_doc_id;
                  return (
                    <EdgeEditor
                      key={edge.edge_id}
                      edge={edge}
                      sourceLabel={source}
                      targetLabel={target}
                      onSave={(next) => void onUpdateEdge(next)}
                      onDelete={() => void onDeleteEdge(edge.edge_id)}
                    />
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function EdgeEditor({
  edge,
  sourceLabel,
  targetLabel,
  onSave,
  onDelete,
}: {
  edge: GraphEdge;
  sourceLabel: string;
  targetLabel: string;
  onSave: (edge: GraphEdge) => void;
  onDelete: () => void;
}) {
  const [relationType, setRelationType] = useState(edge.relation_type);
  const [description, setDescription] = useState(edge.description || "");

  useEffect(() => {
    setRelationType(edge.relation_type);
    setDescription(edge.description || "");
  }, [edge.relation_type, edge.description]);

  return (
    <div style={{ border: "1px solid rgba(255,255,255,0.05)", borderRadius: 8, padding: "12px", background: "rgba(255,255,255,0.02)" }}>
      <div style={{ fontSize: 13, fontWeight: 500, color: "#E2E8F0", marginBottom: 10 }}>
        {shorten(sourceLabel, 18)} <span style={{ color: "#64748B", margin: "0 6px" }}>→</span> {shorten(targetLabel, 18)}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <input 
          style={{ flex: "1 1 120px", padding: "6px 10px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", boxSizing: "border-box" }} 
          value={relationType} 
          onChange={(e) => setRelationType(e.target.value)} 
          placeholder="关系类型"
        />
        <input 
          style={{ flex: "2 1 200px", padding: "6px 10px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", boxSizing: "border-box" }} 
          value={description} 
          onChange={(e) => setDescription(e.target.value)} 
          placeholder="描述" 
        />
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
        <button 
          style={{ padding: "4px 10px", fontSize: 12, background: "transparent", color: "#EF4444", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 4, cursor: "pointer", transition: "all 0.2s" }} 
          onClick={onDelete}
          onMouseEnter={(e) => Object.assign(e.currentTarget.style, { background: "rgba(239,68,68,0.1)" })}
          onMouseLeave={(e) => Object.assign(e.currentTarget.style, { background: "transparent" })}
        >
          删除
        </button>
        <button 
          style={{ padding: "4px 10px", fontSize: 12, background: "transparent", color: "#3B82F6", border: "1px solid rgba(59,130,246,0.3)", borderRadius: 4, cursor: "pointer", transition: "all 0.2s" }} 
          onClick={() => onSave({ ...edge, relation_type: relationType, description })}
          onMouseEnter={(e) => Object.assign(e.currentTarget.style, { background: "rgba(59,130,246,0.1)" })}
          onMouseLeave={(e) => Object.assign(e.currentTarget.style, { background: "transparent" })}
        >
          保存修改
        </button>
      </div>
    </div>
  );
}
