import { useState, type FormEvent } from "react";
import { listRepos, registerRepo } from "../api";
import { LinkButton } from "../components/Layout";
import { useAsync } from "../components/useAsync";
import { EmptyState, ErrorBanner, Field, Loading, PageHeader, Panel, StatusBadge, formatDate, shortSha } from "../components/ui";

export function ReposRoute({ navigate }: { navigate: (path: string) => void }) {
  const reposState = useAsync(listRepos, []);
  const [name, setName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      await registerRepo({ name, local_path: localPath });
      setName("");
      setLocalPath("");
      reposState.refresh();
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSubmitting(false);
    }
  }

  const repos = reposState.data ?? [];

  return (
    <>
      <PageHeader title="Registered Repos" />
      <ErrorBanner message={reposState.error ?? formError} />
      <Panel title="Register Local Path">
        <form className="form-grid" onSubmit={onSubmit}>
          <Field label="Name">
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </Field>
          <Field label="Local path">
            <input value={localPath} onChange={(event) => setLocalPath(event.target.value)} required />
          </Field>
          <button type="submit" disabled={submitting}>
            {submitting ? "Registering" : "Register"}
          </button>
        </form>
      </Panel>
      <Panel title="Repos">
        {reposState.loading ? <Loading /> : null}
        {repos.length === 0 && !reposState.loading ? (
          <EmptyState>No repos registered</EmptyState>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Default branch</th>
                <th>Commit</th>
                <th>Dirty</th>
                <th>Config</th>
                <th>Indexed</th>
              </tr>
            </thead>
            <tbody>
              {repos.map((repo) => (
                <tr key={repo.id}>
                  <td>
                    <LinkButton to={`/repos/${repo.id}`} navigate={navigate}>
                      {repo.name}
                    </LinkButton>
                    <div className="subtle path-cell">{repo.local_path}</div>
                  </td>
                  <td>{repo.default_branch}</td>
                  <td className="mono">{shortSha(repo.current_commit)}</td>
                  <td>{repo.dirty_state}</td>
                  <td>
                    <StatusBadge status={repo.project_config_status} />
                  </td>
                  <td>{formatDate(repo.last_indexed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
