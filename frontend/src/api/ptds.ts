import { http } from "./client";
import { TreeFolder, UploadInitResponse, FileViewResponse, FolderCreateRequest, FolderRenameRequest, FileBrief } from "../types";

interface SearchResult {
  items: FileBrief[];
  total: number;
}

export async function getSpaceTree(spaceId: string): Promise<TreeFolder[]> {
  console.log("[ptds] 获取空间目录树:", spaceId);
  const result = await http<TreeFolder[]>(`/api/v1/spaces/${spaceId}/tree`);
  console.log("[ptds] 获取目录树成功，数量:", result.length);
  return result;
}

function collectFiles(folder: TreeFolder, files: FileBrief[] = []): FileBrief[] {
  files.push(...folder.files);
  for (const child of folder.children) {
    collectFiles(child, files);
  }
  return files;
}

export async function searchFiles(params: { spaceId: string; q?: string; folderId?: string }): Promise<SearchResult> {
  console.log("[ptds] 搜索文件:", params);
  
  const tree = await getSpaceTree(params.spaceId);
  let allFiles: FileBrief[] = [];
  
  for (const root of tree) {
    collectFiles(root, allFiles);
  }
  
  let filtered = allFiles;
  
  if (params.q) {
    const q = params.q.toLowerCase();
    filtered = allFiles.filter(f => f.name.toLowerCase().includes(q));
  }
  
  if (params.folderId) {
    const folderIdNum = parseInt(params.folderId, 10);
    const folder = findFolderById(tree, folderIdNum);
    if (folder) {
      filtered = folder.files;
    } else {
      filtered = [];
    }
  }
  
  console.log("[ptds] 搜索完成:", filtered.length);
  return { items: filtered, total: filtered.length };
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

export async function createFolder(spaceId: string, data: FolderCreateRequest): Promise<void> {
  console.log("[ptds] 创建文件夹:", spaceId, data);
  await http(`/api/v1/spaces/${spaceId}/folders`, {
    method: "POST",
    json: data,
  });
  console.log("[ptds] 创建文件夹成功");
}

export async function renameFolder(spaceId: string, folderPublicId: string, newName: string): Promise<void> {
  console.log("[ptds] 重命名文件夹:", folderPublicId, newName);
  await http(`/api/v1/spaces/${spaceId}/folders/${folderPublicId}/rename`, {
    method: "PATCH",
    json: { new_name: newName } as FolderRenameRequest,
  });
  console.log("[ptds] 重命名文件夹成功");
}

export async function initUpload(
  spaceId: string,
  folderId: number,
  filename: string,
  sizeBytes: number
): Promise<UploadInitResponse> {
  console.log("[ptds] 初始化上传:", { spaceId, folderId, filename, sizeBytes });
  const result = await http<UploadInitResponse>(
    `/api/v1/spaces/${spaceId}/files/upload-init?folder_id=${folderId}&filename=${encodeURIComponent(filename)}&size_bytes=${sizeBytes}`,
    { method: "POST" }
  );
  console.log("[ptds] 初始化上传成功:", result.upload_id);
  return result;
}

export async function completeUpload(spaceId: string, uploadId: string, objectKey: string): Promise<void> {
  console.log("[ptds] 完成上传:", { spaceId, uploadId, objectKey });
  await http(`/api/v1/spaces/${spaceId}/files/upload-complete?upload_id=${uploadId}&object_key=${encodeURIComponent(objectKey)}`, {
    method: "POST",
  });
  console.log("[ptds] 完成上传成功");
}

export async function getFileView(spaceId: string, filePublicId: string): Promise<FileViewResponse> {
  console.log("[ptds] 获取文件查看链接:", { spaceId, filePublicId });
  const result = await http<FileViewResponse>(`/api/v1/spaces/${spaceId}/files/${filePublicId}/view`);
  console.log("[ptds] 获取文件链接成功");
  return result;
}

export async function renameFile(spaceId: string, filePublicId: string, newName: string): Promise<void> {
  console.log("[ptds] 重命名文件:", { spaceId, filePublicId, newName });
  await http(`/api/v1/spaces/${spaceId}/files/${filePublicId}/rename?new_name=${encodeURIComponent(newName)}`, {
    method: "PATCH",
  });
  console.log("[ptds] 重命名文件成功");
}

export async function uploadFileToMinio(presignedUrl: string, file: File): Promise<void> {
  console.log("[ptds] 上传文件到 MinIO:", file.name);
  await fetch(presignedUrl, {
    method: "PUT",
    body: file,
    headers: {
      "Content-Type": file.type,
    },
  });
  console.log("[ptds] MinIO 上传完成");
}

export async function uploadFile(
  spaceId: string,
  folderId: number,
  file: File,
  onProgress?: (progress: number) => void
): Promise<void> {
  console.log("[ptds] 开始上传文件:", file.name);
  
  const initResult = await initUpload(spaceId, folderId, file.name, file.size);
  
  await uploadFileToMinio(initResult.presigned_url, file);
  
  await completeUpload(spaceId, initResult.upload_id, initResult.object_key);
  
  console.log("[ptds] 文件上传完成:", file.name);
}