import { useWorkbench } from "../store/workbench";
import ChatTab from "../worktabs/ChatTab";
import MarkdownTab from "../worktabs/MarkdownTab";
import GraphTab from "../worktabs/GraphTab";
import FilePreviewTab from "../worktabs/FilePreviewTab";
import AssetTab from "../worktabs/AssetTab";

export default function EditorArea() {
  const tabs = useWorkbench(s => s.tabs);
  const activeTabId = useWorkbench(s => s.activeTabId);

  const active = tabs.find(t => t.id === activeTabId) ?? tabs[0];

  return (
    <>
      <div className="editor">
        <div key={active.id} className="editor-pane fade-in-tab">
          {active.kind === "chat" && <ChatTab tab={active} />}
          {active.kind === "markdown" && <MarkdownTab tab={active} />}
          {active.kind === "kg" && <GraphTab tab={active} />}
          {active.kind === "filePreview" && <FilePreviewTab tab={active} />}
          {active.kind === "asset" && <AssetTab tab={active} />}
        </div>
      </div>
    </>
  );
}
