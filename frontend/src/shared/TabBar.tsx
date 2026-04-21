import { useWorkbench } from "../store/workbench";

export default function TabBar() {
  const tabs = useWorkbench(s => s.tabs);
  const activeTabId = useWorkbench(s => s.activeTabId);
  const setActiveTab = useWorkbench(s => s.setActiveTab);
  const closeTab = useWorkbench(s => s.closeTab);
  const openTab = useWorkbench(s => s.openTab);

  return (
    <div className="tabbar" aria-label="Tabs">
      {tabs.map(t => (
        <div
          key={t.id}
          className={"tab" + (t.id === activeTabId ? " active" : "")}
          onClick={() => setActiveTab(t.id)}
          role="button"
          aria-label={`Tab ${t.title}`}
        >
          <span>{t.title}</span>
          {t.id !== "tab-chat" && (
            <span
              className="close"
              title="Close"
              onClick={(e) => { e.stopPropagation(); closeTab(t.id); }}
            >
              ✕
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
