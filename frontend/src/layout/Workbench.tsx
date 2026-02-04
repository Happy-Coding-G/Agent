import ActivityBar from "./ActivityBar";
import SideBar from "./SideBar";
import EditorArea from "./EditorArea";
import BottomPanel from "./BottomPanel";
import StatusBar from "./StatusBar";
import Splitter from "../shared/Splitter";
import { useWorkbench } from "../store/workbench";
import { useEffect } from "react";

export default function Workbench() {
  const sidebarWidth = useWorkbench(s => s.sidebarWidth);
  const setSidebarWidth = useWorkbench(s => s.setSidebarWidth);

  const bottomHeight = useWorkbench(s => s.bottomHeight);
  const setBottomHeight = useWorkbench(s => s.setBottomHeight);

  // 初始化 CSS 变量
  useEffect(() => {
    document.documentElement.style.setProperty("--sidebar-w", `${sidebarWidth}px`);
    document.documentElement.style.setProperty("--bottom-h", `${bottomHeight}px`);
  }, [sidebarWidth, bottomHeight]);

  return (
    <div className="vscode-root">
      <div className="workbench">
        <ActivityBar />
        <div className="mainarea">
          <div className="sidebar">
            <SideBar />
          </div>

          <Splitter
            axis="x"
            onDrag={(delta) => setSidebarWidth(sidebarWidth + delta)}
            ariaLabel="Resize sidebar"
          />

          <div className="editorwrap">
            <EditorArea />

            <Splitter
              axis="y"
              onDrag={(delta) => setBottomHeight(bottomHeight - delta)}
              ariaLabel="Resize bottom panel"
            />

            <BottomPanel />
          </div>
        </div>
      </div>
      <StatusBar />
    </div>
  );
}
