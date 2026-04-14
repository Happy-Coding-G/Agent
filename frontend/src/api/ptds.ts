import { http } from "./client";
import {
  AgentChatResponse,
  AgentTask,
  AssetDetail,
  AssetSummary,
  FileBrief,
  FileQueryResult,
  FileViewResponse,
  FolderCreateRequest,
  FolderRenameRequest,
  GraphData,
  GraphEdge,
  GraphNode,
  MarkdownDocDetail,
  MarkdownDocSummary,
  TreeFolder,
  UploadInitResponse,
} from "../types";

interface SearchResult {
  items: FileBrief[];
  total: number;
}

function collectFiles(folder: TreeFolder, files: FileBrief[] = []): FileBrief[] {
  files.push(...folder.files);
  for (const child of folder.children) {
    collectFiles(child, files);
  }
  return files;
}

function findFolderById(folders: TreeFolder[], id: number): TreeFolder | null {
  for (const folder of folders) {
    if (folder.id === id) return folder;
    if (folder.children.length > 0) {
      const found = findFolderById(folder.children, id);
      if (found) return found;
    }
  }
  return null;
}

// =============================================================================
// Agent-First API layer
// All read operations are proxied through /agent/chat.
// Write operations that require precise parameters are deprecated; use Chat.
// =============================================================================

import { streamSSE } from "./client";

export async function agentChat(
  message: string,
  spaceId: string,
  context?: Record<string, unknown>
): Promise<AgentChatResponse> {
  return await http<AgentChatResponse>("/api/v1/agent/chat", {
    method: "POST",
    json: { message, space_id: spaceId, context },
  });
}

export async function agentChatStream(
  message: string,
  spaceId: string,
  onEvent: (data: { type: string; data: unknown }) => void
): Promise<void> {
  await streamSSE("/api/v1/agent/chat/stream", { message, space_id: spaceId }, (dataLine) => {
    if (dataLine === "[DONE]") return;
    try {
      const data = JSON.parse(dataLine);
      onEvent(data);
    } catch {
      // Ignore parse errors
    }
  });
}

/** Generic helper: invoke a tool via Agent chat and pick the raw tool result. */
async function agentInvoke(message: string, spaceId: string) {
  const res = await agentChat(message, spaceId);
  const result = (res.result || {}) as Record<string, unknown>;
  return {
    answer: typeof result.answer === "string" ? result.answer : undefined,
    toolResults: Array.isArray(result.tool_results) ? result.tool_results : [],
  };
}

function pickToolResult(toolResults: any[], toolName: string, predicate?: (r: any) => boolean) {
  return toolResults.find((r) => r.tool === toolName && (predicate ? predicate(r) : true));
}

// =============================================================================
// Spaces / Files (Read via Agent, Write via Chat)
// =============================================================================

export async function getSpaceTree(spaceId: string): Promise<TreeFolder[]> {
  const { toolResults } = await agentInvoke("列出当前空间的文件目录树", spaceId);
  const tr = pickToolResult(toolResults, "file_manage", (r) => r.result?.action === "list_tree");
  return (tr?.result?.tree || []) as TreeFolder[];
}

export async function searchFiles(params: { spaceId: string; q?: string; folderId?: string }): Promise<SearchResult> {
  const tree = await getSpaceTree(params.spaceId);
  let allFiles: FileBrief[] = [];
  for (const root of tree) {
    collectFiles(root, allFiles);
  }

  let filtered = allFiles;
  if (params.q) {
    const q = params.q.toLowerCase();
    filtered = allFiles.filter((f) => f.name.toLowerCase().includes(q));
  }

  if (params.folderId) {
    const folderIdNum = parseInt(params.folderId, 10);
    const folder = findFolderById(tree, folderIdNum);
    filtered = folder ? folder.files : [];
  }

  return { items: filtered, total: filtered.length };
}

export async function createFolder(_spaceId: string, _data: FolderCreateRequest): Promise<void> {
  throw new Error("文件夹创建已迁移到 Agent Chat，请在聊天窗口发送指令，例如：创建一个名为 XXX 的文件夹");
}

export async function renameFolder(_spaceId: string, _folderPublicId: string, _newName: string): Promise<void> {
  throw new Error("文件夹重命名已迁移到 Agent Chat，请在聊天窗口发送指令");
}

export async function initUpload(
  _spaceId: string,
  _folderPublicId: string,
  _filename: string,
  _sizeBytes: number,
): Promise<UploadInitResponse> {
  throw new Error("文件上传已迁移到 Agent Chat，请在聊天窗口发送指令，例如：上传文件");
}

export async function completeUpload(_spaceId: string, _uploadId: string, _objectKey: string): Promise<void> {
  throw new Error("文件上传已迁移到 Agent Chat，请在聊天窗口发送指令");
}

export async function getFileView(_spaceId: string, _filePublicId: string): Promise<FileViewResponse> {
  throw new Error("文件预览已迁移到 Agent Chat，请在聊天窗口发送指令");
}

export async function renameFile(_spaceId: string, _filePublicId: string, _newName: string): Promise<void> {
  throw new Error("文件重命名已迁移到 Agent Chat，请在聊天窗口发送指令");
}

export async function uploadFileToMinio(uploadUrl: string, file: File, onProgress?: (progress: number) => void): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        const progress = Math.round((event.loaded / event.total) * 100);
        onProgress(progress);
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload failed: ${xhr.status} ${xhr.statusText}`));
      }
    });

    xhr.addEventListener("error", () => {
      reject(new Error("Network error during upload"));
    });

    xhr.open("PUT", uploadUrl);
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.send(file);
  });
}

export async function uploadFile(
  _spaceId: string,
  _folderPublicId: string,
  _file: File,
  _onProgress?: (progress: number) => void,
): Promise<void> {
  throw new Error("文件上传已迁移到 Agent Chat，请在聊天窗口发送指令，例如：上传文件");
}

// =============================================================================
// Markdown (Read via Agent, Save via Chat)
// =============================================================================

export async function listMarkdownDocs(spaceId: string): Promise<MarkdownDocSummary[]> {
  const { toolResults } = await agentInvoke("列出当前空间的所有 Markdown 文档", spaceId);
  const tr = pickToolResult(toolResults, "markdown_manage", (r) => r.result?.action === "list");
  return (tr?.result?.documents || []) as MarkdownDocSummary[];
}

export async function getMarkdownDoc(spaceId: string, docId: string): Promise<MarkdownDocDetail> {
  const { toolResults } = await agentInvoke(`读取 Markdown 文档 ${docId}`, spaceId);
  const tr = pickToolResult(toolResults, "markdown_manage", (r) => r.result?.action === "get");
  const doc = tr?.result?.document as MarkdownDocDetail | undefined;
  if (!doc) {
    throw new Error("未能通过 Agent 获取 Markdown 文档，请重试");
  }
  return doc;
}

export async function saveMarkdownDoc(
  _spaceId: string,
  _docId: string,
  _payload: { markdown_text: string; title?: string },
): Promise<MarkdownDocDetail> {
  throw new Error("Markdown 编辑保存功能已移除，当前仅支持查看。如需修改内容，请通过 Agent Chat 进行。");
}

// =============================================================================
// Knowledge Graph (Read via Agent, Write via Chat)
// =============================================================================

export async function getKnowledgeGraph(spaceId: string): Promise<GraphData> {
  const { toolResults } = await agentInvoke("查看当前空间的知识图谱", spaceId);
  const tr = pickToolResult(toolResults, "graph_manage", (r) => r.result?.action === "get" || r.result?.graph);
  return (tr?.result?.graph || { nodes: [], edges: [] }) as GraphData;
}

export async function updateGraphNode(
  _spaceId: string,
  _docId: string,
  _payload: { label?: string; description?: string; tags?: string[] },
): Promise<GraphNode> {
  throw new Error("图谱节点编辑已迁移到 Agent Chat，请在聊天窗口发送指令");
}

export async function createGraphEdge(
  _spaceId: string,
  _payload: {
    source_doc_id: string;
    target_doc_id: string;
    relation_type: string;
    description?: string;
  },
): Promise<GraphEdge> {
  throw new Error("图谱边创建已迁移到 Agent Chat，请在聊天窗口发送指令");
}

export async function updateGraphEdge(
  _spaceId: string,
  _edgeId: string,
  _payload: { relation_type?: string; description?: string },
): Promise<GraphEdge> {
  throw new Error("图谱边更新已迁移到 Agent Chat，请在聊天窗口发送指令");
}

export async function deleteGraphEdge(_spaceId: string, _edgeId: string): Promise<void> {
  throw new Error("图谱边删除已迁移到 Agent Chat，请在聊天窗口发送指令");
}

// =============================================================================
// Assets (Read/Generate via Agent)
// =============================================================================

export async function listAssets(spaceId: string): Promise<AssetSummary[]> {
  const { toolResults } = await agentInvoke("列出当前空间的所有数字资产", spaceId);
  const tr = pickToolResult(toolResults, "asset_manage", (r) => r.result?.action === "list");
  return (tr?.result?.assets || []) as AssetSummary[];
}

export async function getAssetDetail(spaceId: string, assetId: string): Promise<AssetDetail> {
  const { toolResults } = await agentInvoke(`查看资产 ${assetId} 的详细信息`, spaceId);
  const tr = pickToolResult(toolResults, "asset_manage", (r) => r.result?.action === "get");
  const asset = tr?.result?.asset as AssetDetail | undefined;
  if (!asset) {
    throw new Error("未能通过 Agent 获取资产详情");
  }
  return asset;
}

export async function generateAsset(spaceId: string, prompt?: string): Promise<AssetDetail> {
  const { toolResults } = await agentInvoke(
    `生成数字资产：${prompt || "基于当前空间内容生成知识资产报告"}`,
    spaceId
  );
  const tr = pickToolResult(toolResults, "asset_manage", (r) => r.result?.action === "generate");
  const asset = tr?.result?.asset as AssetDetail | undefined;
  if (!asset) {
    throw new Error("资产生成失败，请通过 Chat 重试");
  }
  return asset;
}

// =============================================================================
// Trade (Deprecated - use Chat)
// =============================================================================

function notAvailableInAgentFirst(feature: string): never {
  throw new Error(`${feature} 已迁移到 Agent Chat，请在聊天窗口发送交易相关指令，例如：我要出售资产 / 购买资产`);
}

export async function getTradePrivacyPolicy(_spaceId: string): Promise<any> {
  return notAvailableInAgentFirst("隐私政策查询");
}

export async function getTradeWallet(): Promise<any> {
  return notAvailableInAgentFirst("钱包查询");
}

export async function listTradeMarket(): Promise<any> {
  return notAvailableInAgentFirst("市场列表");
}

export async function listSpaceTradeListings(_spaceId: string): Promise<any> {
  return notAvailableInAgentFirst("我的挂牌");
}

export async function listTradeOrders(): Promise<any> {
  return notAvailableInAgentFirst("订单列表");
}

export async function listTradeYieldJournal(_spaceId: string): Promise<any> {
  return notAvailableInAgentFirst("收益日志");
}

export async function createTradeListing(_spaceId: string, _payload: any): Promise<any> {
  return notAvailableInAgentFirst("创建挂牌");
}

export async function purchaseTradeListing(_listingId: string): Promise<any> {
  return notAvailableInAgentFirst("购买资产");
}

export async function runTradeAutoYield(_spaceId: string, _strategy?: string): Promise<any> {
  return notAvailableInAgentFirst("自动收益");
}

export async function getTradeOrderDelivery(_orderId: string): Promise<any> {
  return notAvailableInAgentFirst("订单交付");
}

// =============================================================================
// Agent Tasks
// =============================================================================

export async function createAgentTask(
  agentType: string,
  inputData: Record<string, unknown>,
  spaceId: string
): Promise<AgentTask> {
  return await http<AgentTask>("/api/v1/agent/tasks", {
    method: "POST",
    json: { agent_type: agentType, input_data: inputData, space_id: spaceId },
  });
}

export async function getAgentTaskStatus(taskId: string): Promise<{ task_id: string; status: string; progress: number; result?: any }> {
  return await http<{ task_id: string; status: string; progress: number; result?: any }>(`/api/v1/agent/tasks/${taskId}`);
}

// =============================================================================
// Legacy agent sub-endpoints (removed in Agent-First architecture)
// =============================================================================

export async function fileQuery(query: string, spaceId: string): Promise<FileQueryResult> {
  const { answer } = await agentInvoke(`文件查询：${query}`, spaceId);
  return { files: [], error: answer } as FileQueryResult;
}

export async function organizeAssets(
  assetIds: string[],
  spaceId: string,
  _generateReport = true
): Promise<{ status: string; asset_count: number; message: string }> {
  const { toolResults } = await agentInvoke(`整理并聚类资产：${assetIds.join(", ")}`, spaceId);
  const tr = pickToolResult(toolResults, "asset_organize");
  const success = !!tr?.result?.success;
  return {
    status: success ? "completed" : "failed",
    asset_count: assetIds.length,
    message: tr?.result?.message || "请查看 Chat 窗口获取详细结果",
  };
}

export async function getAssetClusters(spaceId: string): Promise<any[]> {
  const { toolResults } = await agentInvoke("查看资产聚类结果", spaceId);
  const tr = pickToolResult(toolResults, "asset_organize");
  return (tr?.result?.clusters || []) as any[];
}

export async function triggerReview(
  docId: string,
  spaceId: string,
  reviewType: "quality" | "compliance" | "completeness" = "quality"
): Promise<any> {
  const { toolResults } = await agentInvoke(`审查文档 ${docId}，类型：${reviewType}`, spaceId);
  const tr = pickToolResult(toolResults, "review_document");
  return tr?.result || { doc_id: docId, review_type: reviewType, score: 0, passed: false, issues: [], final_status: "pending", rework_count: 0 };
}

