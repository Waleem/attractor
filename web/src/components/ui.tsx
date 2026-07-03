import { useEffect, useState, type ReactNode } from "react";
import type { RunStatus, SettingsEditability } from "../api";

export function PageHeader({
  title,
  eyebrow,
  subline,
  actions
}: {
  title: string;
  eyebrow?: string;
  subline?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {subline ? <div className="page-subline">{subline}</div> : null}
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

export function SectionCard({
  title,
  children,
  actions
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="section-card">
      <div className="section-card-heading">
        <h3>{title}</h3>
        {actions ? <div className="section-card-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function SettingsRow({
  label,
  description,
  value,
  editability
}: {
  label: string;
  description: string;
  value: ReactNode;
  editability: SettingsEditability;
}) {
  return (
    <div className="settings-row">
      <div className="settings-row-copy">
        <dt>{label}</dt>
        <dd>{description}</dd>
      </div>
      <div className="settings-row-value">
        <span>{value}</span>
        <EditabilityTag editability={editability} />
      </div>
    </div>
  );
}

function EditabilityTag({ editability }: { editability: SettingsEditability }) {
  return <span className={`editability-tag editability-${editability}`}>{formatEditability(editability)}</span>;
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
  const semanticStatus = statusSemantic(status);
  const label = formatStatus(status);
  return (
    <span className={`status status-${semanticStatus}`} aria-label={label}>
      <StatusDot status={status} />
      <span>{label}</span>
    </span>
  );
}

export const StatusPill = StatusBadge;

export function StatusDot({ status }: { status: RunStatus | string }) {
  return <span className={`status-dot status-dot-${statusSemantic(status)}`} aria-hidden="true" />;
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const feedback =
    state === "copied" ? "Copied to clipboard" : state === "failed" ? "Copy failed" : "";
  const buttonLabel = state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : label;

  useEffect(() => {
    if (state === "idle") {
      return;
    }
    const timer = window.setTimeout(() => setState("idle"), 1800);
    return () => window.clearTimeout(timer);
  }, [state]);

  async function copyValue() {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
  }

  return (
    <>
      <button
        type="button"
        className="icon-button secondary"
        title={buttonLabel}
        aria-label={buttonLabel}
        onClick={() => void copyValue()}
      >
        Copy
      </button>
      <span className="sr-only" aria-live="polite">
        {feedback}
      </span>
    </>
  );
}

export function TruncatedValue({ value }: { value: string }) {
  return (
    <span className="truncate mono" title={value}>
      {value}
    </span>
  );
}

export function CopyableTruncatedValue({ value }: { value: string }) {
  return (
    <span className="copyable-value">
      <TruncatedValue value={value} />
      <CopyButton value={value} />
    </span>
  );
}

export function RelativeTime({ value }: { value: string | null | undefined }) {
  return <time dateTime={value ?? undefined}>{formatRelativeTime(value)}</time>;
}

export function DiffViewer({
  patch,
  truncated
}: {
  patch: string | null | undefined;
  truncated?: boolean;
}) {
  if (!patch) {
    return <EmptyState>No patch content available</EmptyState>;
  }
  return (
    <>
      <pre className="diff-code">{patch}</pre>
      {truncated ? <div className="subtle">Patch truncated at 60,000 characters.</div> : null}
    </>
  );
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

function formatEditability(value: SettingsEditability): string {
  if (value === "restart-required") {
    return "restart required";
  }
  if (value === "read-only") {
    return "read only";
  }
  return value;
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) {
    return "None";
  }
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }
  const deltaSeconds = Math.round((date.valueOf() - Date.now()) / 1000);
  const absoluteSeconds = Math.abs(deltaSeconds);
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["week", 604_800],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
    ["second", 1],
  ];
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, secondsPerUnit] of units) {
    if (absoluteSeconds >= secondsPerUnit || unit === "second") {
      return formatter.format(Math.round(deltaSeconds / secondsPerUnit), unit);
    }
  }
  return formatter.format(deltaSeconds, "second");
}

export function formatDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) {
    return "Not started";
  }
  const startDate = new Date(start);
  const endDate = end ? new Date(end) : new Date();
  if (Number.isNaN(startDate.valueOf()) || Number.isNaN(endDate.valueOf())) {
    return "Unknown";
  }
  const seconds = Math.max(0, Math.round((endDate.valueOf() - startDate.valueOf()) / 1000));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) {
    return `${minutes}m ${remainingSeconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
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

function statusSemantic(status: string): "queued" | "running" | "waiting" | "completed" | "failed" | "neutral" {
  if (["queued", "preparing"].includes(status)) {
    return "queued";
  }
  if (["running"].includes(status)) {
    return "running";
  }
  if (["waiting_for_approval", "writeback_pending"].includes(status)) {
    return "waiting";
  }
  if (["completed", "writeback_applied", "valid", "ok", "configured"].includes(status)) {
    return "completed";
  }
  if (["failed", "cancelled", "writeback_failed", "invalid", "error", "unconfigured"].includes(status)) {
    return "failed";
  }

  const tone = statusTone(status);
  if (tone === "good") {
    return "completed";
  }
  if (tone === "warn") {
    return "waiting";
  }
  if (tone === "bad") {
    return "failed";
  }
  return "neutral";
}

function formatStatus(status: string): string {
  return status.replaceAll("_", " ");
}
