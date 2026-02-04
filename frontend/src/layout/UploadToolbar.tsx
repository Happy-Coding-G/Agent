import { useRef, useState } from "react";
import { uploadFile } from "../api/ptds";
import { useWorkbench } from "../store/workbench";
import { useAuth } from "../store/auth";

export default function UploadToolbar() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const space = useAuth(s => s.currentSpace);
  const log = useWorkbench(s => s.log);
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setFileName(file.name);
    setError(null);
    handleUpload(file);
  };

  const handleUpload = async (file: File) => {
    if (!space?.public_id) {
      setError("请先选择空间");
      return;
    }
    
    setUploading(true);
    setError(null);
    try {
      await uploadFile(space.public_id, 1, file);
      log(`[Upload] 成功上传文件: ${file.name}`);
      setFileName("");
    } catch (error: any) {
      const errorMsg = error?.message ?? String(error);
      log(`[Upload] 上传失败: ${errorMsg}`);
      setError(errorMsg);
      console.error("[UploadToolbar] 上传失败详情:", error);
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const triggerFileSelect = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="upload-toolbar">
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: "none" }}
        onChange={handleFileSelect}
        disabled={uploading}
      />
      <div className="row" style={{ gap: 8, alignItems: "center" }}>
        <button
          className="btn btn-primary"
          onClick={triggerFileSelect}
          disabled={uploading}
          title="上传文件"
        >
          {uploading ? "上传中..." : "📤 上传文件"}
        </button>
        {fileName && (
          <span className="badge" style={{ fontSize: 12 }}>
            {fileName}
          </span>
        )}
        {error && (
          <span className="badge" style={{ fontSize: 12, color: "var(--danger)", borderColor: "var(--danger)" }}>
            ❌ {error}
          </span>
        )}
      </div>
    </div>
  );
}