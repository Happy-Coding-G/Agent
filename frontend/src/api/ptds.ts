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
  Space,
  TreeFolder,
  UploadInitResponse,
} from "../types";

import { streamSSE } from "./client";

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
// Agent Chat
// =============================================================================

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

// =============================================================================
// Spaces
// =============================================================================

export async function getSpaces(): Promise<Space[]> {
  return await http<Space[]>("/api/v1/spaces");
}

export async function createSpace(name: string): Promise<Space> {
  return await http<Space>("/api/v1/spaces", {
    method: "POST",
    json: { name },
  });
}

export async function deleteSpace(spaceId: string): Promise<void> {
  await http<void>(`/api/v1/spaces/${spaceId}`, { method: "DELETE" });
}

export async function switchSpace(spaceId: string): Promise<Space> {
  return await http<Space>(`/api/v1/spaces/${spaceId}/switch`, { method: "POST" });
}

// =============================================================================
// Files
// =============================================================================

export async function getSpaceTree(spaceId: string): Promise<TreeFolder[]> {
  return await http<TreeFolder[]>(`/api/v1/spaces/${spaceId}/tree`);
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

export async function createFolder(spaceId: string, data: FolderCreateRequest): Promise<void> {
  await http(`/api/v1/spaces/${spaceId}/folders`, {
    method: "POST",
    json: data,
  });
}

export async function renameFolder(spaceId: string, folderPublicId: string, newName: string): Promise<void> {
  await http(`/api/v1/spaces/${spaceId}/folders/${folderPublicId}/rename`, {
    method: "PATCH",
    json: { new_name: newName },
  });
}

export async function initUpload(
  spaceId: string,
  folderId: string,
  filename: string,
  sizeBytes: number,
): Promise<UploadInitResponse> {
  return await http<UploadInitResponse>(
    `/api/v1/spaces/${spaceId}/files/upload-init?folder_id=${encodeURIComponent(folderId)}&filename=${encodeURIComponent(filename)}&size_bytes=${sizeBytes}`,
    { method: "POST" }
  );
}

export async function completeUpload(spaceId: string, uploadId: string, objectKey: string): Promise<void> {
  await http(
    `/api/v1/spaces/${spaceId}/files/upload-complete?upload_id=${encodeURIComponent(uploadId)}&object_key=${encodeURIComponent(objectKey)}`,
    { method: "POST" }
  );
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
  spaceId: string,
  folderId: string,
  file: File,
  onProgress?: (progress: number) => void,
): Promise<void> {
  const init = await initUpload(spaceId, folderId, file.name, file.size);
  if (!init.upload_url && !init.presigned_url) {
    throw new Error("No upload URL returned");
  }
  await uploadFileToMinio(init.upload_url || init.presigned_url!, file, onProgress);
  await completeUpload(spaceId, init.upload_id, init.object_key);
}

export async function getFileView(_spaceId: string, _filePublicId: string): Promise<FileViewResponse> {
  throw new Error("文件预览已迁移到 Agent Chat，请在聊天窗口发送指令");
}

export async function renameFile(_spaceId: string, _filePublicId: string, _newName: string): Promise<void> {
  throw new Error("文件重命名已迁移到 Agent Chat，请在聊天窗口发送指令");
}

// =============================================================================
// Markdown (Read via Direct API)
// =============================================================================

export async function listMarkdownDocs(spaceId: string): Promise<MarkdownDocSummary[]> {
  return await http<MarkdownDocSummary[]>(`/api/v1/spaces/${spaceId}/markdown-docs`);
}

export async function getMarkdownDoc(spaceId: string, docId: string): Promise<MarkdownDocDetail> {
  return await http<MarkdownDocDetail>(`/api/v1/spaces/${spaceId}/markdown-docs/${docId}`);
}

export async function saveMarkdownDoc(
  _spaceId: string,
  _docId: string,
  _payload: { markdown_text: string; title?: string },
): Promise<MarkdownDocDetail> {
  throw new Error("Markdown 编辑保存功能已移除，当前仅支持查看。如需修改内容，请通过 Agent Chat 进行。");
}

// =============================================================================
// Knowledge Graph (Read via Direct API, Write via Chat)
// =============================================================================

export async function getKnowledgeGraph(spaceId: string): Promise<GraphData> {
  return await http<GraphData>(`/api/v1/spaces/${spaceId}/graph`);
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
// Assets (Read via Direct API, Generate via Agent)
// =============================================================================

export async function listAssets(spaceId: string): Promise<AssetSummary[]> {
  return await http<AssetSummary[]>(`/api/v1/spaces/${spaceId}/assets`);
}

export async function getAssetDetail(spaceId: string, assetId: string): Promise<AssetDetail> {
  return await http<AssetDetail>(`/api/v1/spaces/${spaceId}/assets/${assetId}`);
}

export async function generateAsset(spaceId: string, prompt?: string): Promise<AssetDetail> {
  return await http<AssetDetail>(`/api/v1/spaces/${spaceId}/assets/generate`, {
    method: "POST",
    json: { prompt: prompt || "" },
  });
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
// Legacy agent sub-endpoints (use Chat)
// =============================================================================

export async function fileQuery(query: string, spaceId: string): Promise<FileQueryResult> {
  const res = await agentChat(`文件查询：${query}`, spaceId);
  return { files: [], error: res.error } as FileQueryResult;
}

export async function organizeAssets(
  assetIds: string[],
  spaceId: string,
  _generateReport = true
): Promise<{ status: string; asset_count: number; message: string }> {
  const res = await agentChat(`整理并聚类资产：${assetIds.join(", ")}`, spaceId);
  return {
    status: res.error ? "failed" : "completed",
    asset_count: assetIds.length,
    message: res.error || "请查看 Chat 窗口获取详细结果",
  };
}

export async function getAssetClusters(spaceId: string): Promise<any[]> {
  const res = await agentChat("查看资产聚类结果", spaceId);
  return (res.result?.clusters || []) as any[];
}

export async function triggerReview(
  docId: string,
  spaceId: string,
  reviewType: "quality" | "compliance" | "completeness" = "quality"
): Promise<any> {
  const res = await agentChat(`审查文档 ${docId}，类型：${reviewType}`, spaceId);
  return res.result || { doc_id: docId, review_type: reviewType, score: 0, passed: false, issues: [], final_status: "pending", rework_count: 0 };
}
