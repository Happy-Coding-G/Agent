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
      setError("Please select a space first.");
      return;
    }

    setUploading(true);
    setError(null);
    try {
      await uploadFile(space.public_id, "1", file);
      log(`[Upload] success: ${file.name}`);
      setFileName("");
    } catch (error: any) {
      const errorMsg = error?.message ?? String(error);
      log(`[Upload] failed: ${errorMsg}`);
      setError(errorMsg);
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
          title="Upload file"
        >
          {uploading ? "Uploading..." : "Upload file"}
        </button>
        {fileName && (
          <span className="badge" style={{ fontSize: 12 }}>
            {fileName}
          </span>
        )}
        {error && (
          <span className="badge" style={{ fontSize: 12, color: "var(--danger)", borderColor: "var(--danger)" }}>
            [x] {error}
          </span>
        )}
      </div>
    </div>
  );
}
