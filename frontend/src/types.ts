export type Activity = "explorer" | "search" | "assets" | "kg";

export type TabKind = "chat" | "markdown" | "filePreview" | "kg" | "asset";

export type Tab = {
  id: string;
  kind: TabKind;
  title: string;
  payload?: Record<string, unknown>;
};

export type Space = {
  id: number;
  public_id: string;
  name: string;
  owner_user_id: number;
};

export type FileBrief = {
  public_id: string;
  name: string;
  size_bytes: number | null;
  mime: string | null;
};

export type TreeFolder = {
  id: number;
  public_id: string;
  name: string;
  path_cache: string;
  children: TreeFolder[];
  files: FileBrief[];
};

export type UploadInitResponse = {
  upload_id: string;
  presigned_url: string;
  object_key: string;
};

export type FileViewResponse = {
  url: string;
  expires_in: number;
};

export type User = {
  id: number;
  user_key: string;
  display_name?: string;
};

export type LoginRequest = {
  identifier: string;
  credential: string;
  identity_type: string;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
};

export type RegisterRequest = {
  identifier: string;
  credential: string;
  identity_type: string;
  display_name?: string;
};

export type RegisterResponse = {
  status: string;
  user_id: number;
  message: string;
};

export type FolderCreateRequest = {
  name: string;
  parent_id?: number | null;
};

export type FolderRenameRequest = {
  new_name: string;
};

export type FileRenameRequest = {
  new_name: string;
};