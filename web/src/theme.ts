export type Theme = "slate" | "porcelain";

export const THEME_STORAGE_KEY = "attractor-theme";

type ThemeStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
};

export function isTheme(value: unknown): value is Theme {
  return value === "slate" || value === "porcelain";
}

export function getInitialTheme(): Theme {
  try {
    const storedTheme = getThemeStorage()?.getItem(THEME_STORAGE_KEY);
    return isTheme(storedTheme) ? storedTheme : "slate";
  } catch {
    return "slate";
  }
}

export function setTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    getThemeStorage()?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    return;
  }
}

function getThemeStorage(): ThemeStorage | null {
  const globalStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  if (globalStorageDescriptor && "value" in globalStorageDescriptor) {
    return globalStorageDescriptor.value as ThemeStorage | null;
  }
  if (typeof window !== "undefined") {
    return "localStorage" in window ? window.localStorage : null;
  }
  return null;
}
