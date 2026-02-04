import { create } from "zustand";

type ToastType = "success" | "error" | "warning" | "info";

interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  duration?: number;
}

interface ToastState {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, "id">) => string;
  removeToast: (id: string) => void;
  clearToasts: () => void;
  success: (title: string, message?: string) => string;
  error: (title: string, message?: string) => string;
  warning: (title: string, message?: string) => string;
  info: (title: string, message?: string) => string;
}

const generateId = () => Math.random().toString(36).substring(2, 9);

export const useToast = create<ToastState>((set, get) => ({
  toasts: [],

  addToast: (toast) => {
    const id = generateId();
    const newToast = { ...toast, id };
    set((state) => ({
      toasts: [...state.toasts, newToast],
    }));

    const duration = toast.duration ?? 4000;
    if (duration > 0) {
      setTimeout(() => {
        get().removeToast(id);
      }, duration);
    }

    return id;
  },

  removeToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },

  clearToasts: () => {
    set({ toasts: [] });
  },

  success: (title, message) => {
    return get().addToast({ type: "success", title, message });
  },

  error: (title, message) => {
    return get().addToast({ type: "error", title, message });
  },

  warning: (title, message) => {
    return get().addToast({ type: "warning", title, message });
  },

  info: (title, message) => {
    return get().addToast({ type: "info", title, message });
  },
}));

export default useToast;