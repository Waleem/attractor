import type { ReactNode } from "react";
import type { RunStatus } from "../api";

export function PageHeader({
  title,
  eyebrow,
  actions
}: {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function Panel({
  title,
  children,
  actions
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  tone = "default"
}: {
  label: string;
  value: ReactNode;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  return (
    <div className={`stat stat-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function StatusBadge({ status }: { status: RunStatus | string }) {
  const tone = statusTone(status);
  return <span className={`status status-${tone}`}>{status.replaceAll("_", " ")}</span>;
}

export function EmptyState({ children = "No records" }: { children?: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) {
    return null;
  }
  return <div className="error-banner">{message}</div>;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return <div className="loading">{label}</div>;
}

export function Field({
  label,
  children
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function KeyValue({
  label,
  value
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="key-value">
      <dt>{label}</dt>
      <dd>{value || "None"}</dd>
    </div>
  );
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "None";
  }
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }
  return date.toLocaleString();
}

export function shortSha(value: string | null | undefined): string {
  if (!value) {
    return "None";
  }
  return value.length > 12 ? value.slice(0, 12) : value;
}

export function statusTone(status: string): "good" | "warn" | "bad" | "neutral" {
  if (["completed", "writeback_applied", "valid", "ok"].includes(status)) {
    return "good";
  }
  if (["queued", "preparing", "running", "waiting_for_approval", "writeback_pending"].includes(status)) {
    return "warn";
  }
  if (["failed", "cancelled", "writeback_failed", "invalid", "error"].includes(status)) {
    return "bad";
  }
  return "neutral";
}
