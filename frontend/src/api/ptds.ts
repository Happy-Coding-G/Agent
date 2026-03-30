import { http } from "./client";
import {
  AssetDetail,
  AssetSummary,
  FileBrief,
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
    json: { new_name: newName } as FolderRenameRequest,
  });
}

export async function initUpload(
  spaceId: string,
  folderPublicId: string,
  filename: string,
  sizeBytes: number,
): Promise<UploadInitResponse> {
  return await http<UploadInitResponse>(
    `/api/v1/spaces/${spaceId}/files/upload-init?folder_id=${encodeURIComponent(folderPublicId)}&filename=${encodeURIComponent(filename)}&size_bytes=${sizeBytes}`,
    { method: "POST" },
  );
}

export async function completeUpload(spaceId: string, uploadId: string, objectKey: string): Promise<void> {
  await http(
    `/api/v1/spaces/${spaceId}/files/upload-complete?upload_id=${uploadId}&object_key=${encodeURIComponent(objectKey)}`,
    {
      method: "POST",
    },
  );
}

export async function getFileView(spaceId: string, filePublicId: string): Promise<FileViewResponse> {
  return await http<FileViewResponse>(`/api/v1/spaces/${spaceId}/files/${filePublicId}/view`);
}

export async function renameFile(spaceId: string, filePublicId: string, newName: string): Promise<void> {
  await http(`/api/v1/spaces/${spaceId}/files/${filePublicId}/rename?new_name=${encodeURIComponent(newName)}`, {
    method: "PATCH",
  });
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
  folderPublicId: string,
  file: File,
  onProgress?: (progress: number) => void,
): Promise<void> {
  const initResult = await initUpload(spaceId, folderPublicId, file.name, file.size);
  const uploadUrl = initResult.presigned_url ?? initResult.upload_url;
  if (!uploadUrl) {
    throw new Error("Upload initialization response missing upload URL");
  }

  await uploadFileToMinio(uploadUrl, file, onProgress);
  await completeUpload(spaceId, initResult.upload_id, initResult.object_key);
}

export async function listMarkdownDocs(spaceId: string): Promise<MarkdownDocSummary[]> {
  return await http<MarkdownDocSummary[]>(`/api/v1/spaces/${spaceId}/markdown-docs`);
}

export async function getMarkdownDoc(spaceId: string, docId: string): Promise<MarkdownDocDetail> {
  return await http<MarkdownDocDetail>(`/api/v1/spaces/${spaceId}/markdown-docs/${docId}`);
}

export async function saveMarkdownDoc(
  spaceId: string,
  docId: string,
  payload: { markdown_text: string; title?: string },
): Promise<MarkdownDocDetail> {
  return await http<MarkdownDocDetail>(`/api/v1/spaces/${spaceId}/markdown-docs/${docId}`, {
    method: "PUT",
    json: payload,
    timeoutMs: 120_000,
  });
}

export async function getKnowledgeGraph(spaceId: string): Promise<GraphData> {
  return await http<GraphData>(`/api/v1/spaces/${spaceId}/graph`);
}

export async function updateGraphNode(
  spaceId: string,
  docId: string,
  payload: { label?: string; description?: string; tags?: string[] },
): Promise<GraphNode> {
  return await http<GraphNode>(`/api/v1/spaces/${spaceId}/graph/nodes/${docId}`, {
    method: "PATCH",
    json: payload,
  });
}

export async function createGraphEdge(
  spaceId: string,
  payload: {
    source_doc_id: string;
    target_doc_id: string;
    relation_type: string;
    description?: string;
  },
): Promise<GraphEdge> {
  return await http<GraphEdge>(`/api/v1/spaces/${spaceId}/graph/edges`, {
    method: "POST",
    json: payload,
  });
}

export async function updateGraphEdge(
  spaceId: string,
  edgeId: string,
  payload: { relation_type?: string; description?: string },
): Promise<GraphEdge> {
  return await http<GraphEdge>(`/api/v1/spaces/${spaceId}/graph/edges/${edgeId}`, {
    method: "PATCH",
    json: payload,
  });
}

export async function deleteGraphEdge(spaceId: string, edgeId: string): Promise<void> {
  await http(`/api/v1/spaces/${spaceId}/graph/edges/${edgeId}`, {
    method: "DELETE",
  });
}

export async function listAssets(spaceId: string): Promise<AssetSummary[]> {
  return await http<AssetSummary[]>(`/api/v1/spaces/${spaceId}/assets`);
}

export async function getAssetDetail(spaceId: string, assetId: string): Promise<AssetDetail> {
  return await http<AssetDetail>(`/api/v1/spaces/${spaceId}/assets/${assetId}`);
}

export async function generateAsset(spaceId: string, prompt?: string): Promise<AssetDetail> {
  return await http<AssetDetail>(`/api/v1/spaces/${spaceId}/assets/generate`, {
    method: "POST",
    json: { prompt: prompt ?? null },
    timeoutMs: 120_000,
  });
}

// Note: Trade functionality has been moved to agent-based interaction
// Use agentChat() or agentChatStream() with trade-related queries instead
// Examples:
// - "我要上架资产" / "Create a listing for asset X"
// - "我要购买" / "Purchase listing X"
// - "查看我的钱包" / "Check my wallet balance"

// Agent API
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

export async function createAgentTask(
  agentType: string,
  inputData: Record<string, unknown>,
  spaceId: string
): Promise<AgentTask> {
  return await http<AgentTask>("/api/v1/agent/task", {
    method: "POST",
    json: { agent_type: agentType, input_data: inputData, space_id: spaceId },
  });
}

export async function getAgentTaskStatus(taskId: string): Promise<{ task_id: string; status: string; progress: number }> {
  return await http<{ task_id: string; status: string; progress: number }>(`/api/v1/agent/task/${taskId}/status`);
}

export async function fileQuery(query: string, spaceId: string): Promise<FileQueryResult> {
  return await http<FileQueryResult>("/api/v1/agent/file/query", {
    method: "POST",
    json: { query, space_id: spaceId },
  });
}

export async function organizeAssets(
  assetIds: string[],
  spaceId: string,
  generateReport = true
): Promise<{ status: string; asset_count: number; message: string }> {
  return await http<{ status: string; asset_count: number; message: string }>("/api/v1/agent/asset/organize", {
    method: "POST",
    json: { asset_ids: assetIds, space_id: spaceId, generate_report: generateReport },
  });
}

export async function getAssetClusters(spaceId: string): Promise<AssetCluster[]> {
  return await http<AssetCluster[]>(`/api/v1/agent/clusters?space_id=${spaceId}`);
}

export async function triggerReview(
  docId: string,
  spaceId: string,
  reviewType: "quality" | "compliance" | "completeness" = "quality"
): Promise<ReviewResponse> {
  return await http<ReviewResponse>(`/api/v1/agent/review/${docId}`, {
    method: "POST",
    json: { review_type: reviewType, space_id: spaceId },
  });
}
