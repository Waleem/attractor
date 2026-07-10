import { useState, type ReactNode } from "react";
import { getAppBasePath, toAppHref } from "../appBase";
import { getInitialTheme, setTheme, type Theme } from "../theme";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/repos", label: "Repos" },
  { href: "/runs", label: "Runs" },
  { href: "/approvals", label: "Approvals" },
  { href: "/system", label: "System" },
  { href: "/settings", label: "Settings" }
];

export function Layout({
  path,
  navigate,
  basePath,
  children
}: {
  path: string;
  navigate: (path: string) => void;
  basePath: string;
  children: ReactNode;
}) {
  const [activeTheme, setActiveTheme] = useState<Theme>(() => getInitialTheme());
  const chooseTheme = (theme: Theme) => {
    setTheme(theme);
    setActiveTheme(theme);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href={toAppHref("/", basePath)}
          onClick={(event) => {
            event.preventDefault();
            navigate("/");
          }}
        >
          <span className="brand-mark">A</span>
          <span>Attractor Studio</span>
        </a>
        <nav>
          {navItems.map((item) => (
            <a
              key={item.href}
              href={toAppHref(item.href, basePath)}
              className={path === item.href || (item.href !== "/" && path.startsWith(item.href)) ? "active" : ""}
              onClick={(event) => {
                event.preventDefault();
                navigate(item.href);
              }}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <footer className="sidebar-footer">
          <div className="segmented-control theme-toggle" aria-label="Theme">
            <button
              type="button"
              className={activeTheme === "slate" ? "active" : ""}
              aria-pressed={activeTheme === "slate"}
              onClick={() => chooseTheme("slate")}
            >
              Slate
            </button>
            <button
              type="button"
              className={activeTheme === "porcelain" ? "active" : ""}
              aria-pressed={activeTheme === "porcelain"}
              onClick={() => chooseTheme("porcelain")}
            >
              Porcelain
            </button>
          </div>
        </footer>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}

export function LinkButton({
  to,
  navigate,
  children,
  className = ""
}: {
  to: string;
  navigate: (path: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <a
      className={`link-button ${className}`}
      href={toAppHref(to, getAppBasePath())}
      onClick={(event) => {
        event.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}
