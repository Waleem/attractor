import type { ReactNode } from "react";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/repos", label: "Repos" },
  { href: "/runs", label: "Runs" },
  { href: "/approvals", label: "Approvals" },
  { href: "/system", label: "System" }
];

export function Layout({
  path,
  navigate,
  children
}: {
  path: string;
  navigate: (path: string) => void;
  children: ReactNode;
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="/"
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
              href={item.href}
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
      href={to}
      onClick={(event) => {
        event.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}
