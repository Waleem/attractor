import type { ReactNode } from "react";
import { getAppBasePath, toAppHref } from "../appBase";

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
          <span>Attractor Ops</span>
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
