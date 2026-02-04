import { create } from "zustand";
import { Activity, Tab } from "../types";

type WorkbenchState = {
  spaceId: string;
  spaceRefreshKey: number;
  userId: string;
  activity: Activity;
  tabs: Tab[];
  activeTabId: string;

  bottomLogs: string[];
  sidebarWidth: number;
  bottomHeight: number;

  setSpaceId: (spaceId: string) => void;
  incrementSpaceRefreshKey: () => void;
  setUserId: (userId: string) => void;
  setActivity: (activity: Activity) => void;

  openTab: (tab: Tab) => void;
  closeTab: (tabId: string) => void;
  setActiveTab: (tabId: string) => void;

  log: (line: string) => void;
  addLog: (line: string) => void;
  setSidebarWidth: (w: number) => void;
  setBottomHeight: (h: number) => void;
};

const defaultTabs: Tab[] = [
  { id: "tab-chat", kind: "chat", title: "Chat" },
];

export const useWorkbench = create<WorkbenchState>((set, get) => ({
  spaceId: "",
  spaceRefreshKey: 0,
  userId: "",
  activity: "explorer",
  tabs: defaultTabs,
  activeTabId: defaultTabs[0].id,

  bottomLogs: ["PTDS Workbench ready."],
  sidebarWidth: 300,
  bottomHeight: 220,

  setSpaceId: (spaceId) => set({ spaceId }),
  incrementSpaceRefreshKey: () => set({ spaceRefreshKey: get().spaceRefreshKey + 1 }),
  setUserId: (userId) => set({ userId }),
  setActivity: (activity) => set({ activity }),

  openTab: (tab) => {
    const { tabs } = get();
    const exists = tabs.find(t => t.id === tab.id);
    if (exists) {
      set({ activeTabId: tab.id });
      return;
    }
    set({ tabs: [...tabs, tab], activeTabId: tab.id });
  },

  closeTab: (tabId) => {
    const { tabs, activeTabId } = get();
    const next = tabs.filter(t => t.id !== tabId);
    let nextActive = activeTabId;
    if (activeTabId === tabId) {
      nextActive = next.length ? next[next.length - 1].id : "";
    }
    set({ tabs: next.length ? next : defaultTabs, activeTabId: nextActive || defaultTabs[0].id });
  },

  setActiveTab: (tabId) => set({ activeTabId: tabId }),

  log: (line: string) => set({ bottomLogs: [...get().bottomLogs.slice(-199), line] }),
  addLog: (line: string) => set({ bottomLogs: [...get().bottomLogs.slice(-199), line] }),

  setSidebarWidth: (w) => {
    const clamped = Math.max(220, Math.min(520, w));
    set({ sidebarWidth: clamped });
    document.documentElement.style.setProperty("--sidebar-w", `${clamped}px`);
  },

  setBottomHeight: (h) => {
    const clamped = Math.max(120, Math.min(420, h));
    set({ bottomHeight: clamped });
    document.documentElement.style.setProperty("--bottom-h", `${clamped}px`);
  },
}));
