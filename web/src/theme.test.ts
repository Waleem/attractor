import {
  getInitialTheme,
  isTheme,
  setTheme,
  type Theme
} from "./theme.js";

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}\nexpected: ${String(expected)}\nactual:   ${String(actual)}`);
  }
}

class StorageFixture {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }

  removeItem(key: string) {
    this.values.delete(key);
  }
}

class DocumentElementFixture {
  readonly dataset: { theme?: Theme } = {};
}

function installBrowserFixtures(storedTheme?: string) {
  const storage = new StorageFixture();
  if (storedTheme) {
    storage.setItem("attractor-theme", storedTheme);
  }
  const documentElement = new DocumentElementFixture();
  Object.defineProperty(globalThis, "localStorage", {
    value: storage,
    configurable: true
  });
  Object.defineProperty(globalThis, "document", {
    value: { documentElement },
    configurable: true
  });
  return { storage, documentElement };
}

installBrowserFixtures();
assertEqual(getInitialTheme(), "slate", "defaults to Slate when localStorage is empty");
assertEqual(isTheme("slate"), true, "recognizes Slate");
assertEqual(isTheme("porcelain"), true, "recognizes Porcelain");
assertEqual(isTheme("aurora"), false, "rejects unsupported themes");

installBrowserFixtures("porcelain");
assertEqual(getInitialTheme(), "porcelain", "uses the persisted Porcelain choice");

installBrowserFixtures("aurora");
assertEqual(getInitialTheme(), "slate", "falls back to Slate for unknown stored values");

const { storage, documentElement } = installBrowserFixtures();
setTheme("porcelain");
assertEqual(documentElement.dataset.theme, "porcelain", "setTheme updates the document theme");
assertEqual(storage.getItem("attractor-theme"), "porcelain", "setTheme persists the choice");
