import { create } from "zustand";
import { persist } from "zustand/middleware";
import { User, Space } from "../types";

type AuthState = {
  isAuthenticated: boolean;
  user: User | null;
  token: string | null;
  spaces: Space[];
  currentSpace: Space | null;
  showSpaceManager: boolean;

  login: (user: User, token: string, spaces: Space[], defaultSpace: Space) => void;
  logout: () => void;
  setSpaces: (spaces: Space[]) => void;
  setCurrentSpace: (space: Space) => void;
  addSpace: (space: Space) => void;
  removeSpace: (spaceId: string) => void;
  setToken: (token: string) => void;
  setUser: (user: User) => void;
  setShowSpaceManager: (show: boolean) => void;
};

export const useAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      isAuthenticated: false,
      user: null,
      token: null,
      spaces: [],
      currentSpace: null,
      showSpaceManager: false,

      login: (user, token, spaces, defaultSpace) => {
        set({
          isAuthenticated: true,
          user,
          token,
          spaces,
          currentSpace: defaultSpace,
        });
      },

      logout: () => {
        set({
          isAuthenticated: false,
          user: null,
          token: null,
          spaces: [],
          currentSpace: null,
          showSpaceManager: false,
        });
      },

      setSpaces: (spaces) => set({ spaces }),

      setCurrentSpace: (space) => set({ currentSpace: space }),

      addSpace: (space) => {
        const { spaces } = get();
        set({ spaces: [...spaces, space] });
      },

      removeSpace: (spaceId) => {
        const { spaces, currentSpace } = get();
        const newSpaces = spaces.filter(s => s.public_id !== spaceId);
        const newCurrentSpace = currentSpace?.public_id === spaceId 
          ? (newSpaces.length > 0 ? newSpaces[0] : null)
          : currentSpace;
        set({ spaces: newSpaces, currentSpace: newCurrentSpace });
      },

      setToken: (token) => set({ token }),

      setUser: (user) => set({ user, isAuthenticated: !!user }),

      setShowSpaceManager: (show) => set({ showSpaceManager: show }),
    }),
    {
      name: "auth-storage",
    }
  )
);