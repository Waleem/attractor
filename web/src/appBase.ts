declare global {
  interface Window {
    __ATTRACTOR_BASE_PATH__?: string;
  }
}

const KNOWN_APP_SEGMENTS = ["repos", "workflows", "runs", "approvals", "system", "settings"];

function withoutQueryOrHash(value: string): string {
  return value.split(/[?#]/, 1)[0] ?? "";
}

function pathFromBaseValue(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  try {
    return new URL(trimmed).pathname;
  } catch {
    return trimmed;
  }
}

export function normalizeBasePath(value: string | null | undefined): string {
  if (!value) {
    return "";
  }

  let path = withoutQueryOrHash(pathFromBaseValue(value));
  if (path === "." || path === "./") {
    return "";
  }

  path = path.replace(/\/+$/, "");
  if (!path || path === "/" || path === ".") {
    return "";
  }
  if (!path.startsWith("/")) {
    path = `/${path}`;
  }
  return path;
}

export function inferBasePathFromPathname(pathname: string): string {
  const normalizedPath = pathname.startsWith("/") ? pathname : `/${pathname}`;
  if (normalizedPath === "/") {
    return "";
  }

  for (const segment of KNOWN_APP_SEGMENTS) {
    const appRoute = `/${segment}`;
    const routeIndex = normalizedPath.indexOf(appRoute);
    if (routeIndex === 0) {
      return "";
    }
    if (routeIndex > 0) {
      const nextCharacter = normalizedPath[routeIndex + appRoute.length];
      if (nextCharacter === undefined || nextCharacter === "/" || nextCharacter === "?" || nextCharacter === "#") {
        return normalizeBasePath(normalizedPath.slice(0, routeIndex));
      }
    }
  }

  return "";
}

export function configuredBasePath(): string {
  if (typeof window !== "undefined") {
    const injectedBasePath = normalizeBasePath(window.__ATTRACTOR_BASE_PATH__);
    if (injectedBasePath) {
      return injectedBasePath;
    }
  }

  if (typeof document !== "undefined") {
    const baseElement = document.querySelector<HTMLBaseElement>("base[data-attractor-base]");
    const baseHref = normalizeBasePath(baseElement?.getAttribute("href"));
    if (baseHref) {
      return baseHref;
    }
  }

  const configuredEnvBase = normalizeBasePath(import.meta.env.VITE_APP_BASE_PATH);
  if (configuredEnvBase) {
    return configuredEnvBase;
  }
  return normalizeBasePath(import.meta.env.BASE_URL);
}

export function getAppBasePath(pathname = window.location.pathname): string {
  return configuredBasePath() || inferBasePathFromPathname(pathname);
}

export function stripBasePath(pathname: string, basePath = getAppBasePath(pathname)): string {
  const normalizedPath = pathname.startsWith("/") ? pathname : `/${pathname}`;
  const normalizedBase = normalizeBasePath(basePath);
  if (!normalizedBase) {
    return normalizedPath;
  }
  if (normalizedPath === normalizedBase) {
    return "/";
  }
  if (normalizedPath.startsWith(`${normalizedBase}/`)) {
    return normalizedPath.slice(normalizedBase.length) || "/";
  }
  return normalizedPath;
}

export function toAppHref(routePath: string, basePath = getAppBasePath()): string {
  if (/^[a-z][a-z\d+\-.]*:/i.test(routePath)) {
    return routePath;
  }

  const normalizedBase = normalizeBasePath(basePath);
  const [pathPart, suffix = ""] = routePath.split(/([?#].*)/, 2);
  const normalizedRoute = pathPart.startsWith("/") ? pathPart : `/${pathPart}`;
  if (normalizedRoute === "/") {
    return `${normalizedBase || "/"}${suffix}`;
  }
  return `${normalizedBase}${normalizedRoute}${suffix}`;
}

export function apiPath(
  path: string,
  apiBase = import.meta.env.VITE_API_BASE_URL ?? "",
  basePath = getAppBasePath()
): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const normalizedApiBase = apiBase.trim().replace(/\/+$/, "");
  if (normalizedApiBase) {
    return `${normalizedApiBase}${normalizedPath}`;
  }
  return toAppHref(normalizedPath, basePath);
}
