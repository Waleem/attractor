import { useState, type FormEvent } from "react";
import { browseFilesystem, listRepos, registerRepo, type FsBrowseEntry } from "../api";
import { LinkButton } from "../components/Layout";
import { useAsync } from "../components/useAsync";
import { EmptyState, ErrorBanner, Field, Loading, PageHeader, Panel, StatusBadge, formatDate, shortSha } from "../components/ui";

export function ReposRoute({ navigate }: { navigate: (path: string) => void }) {
  const reposState = useAsync(listRepos, []);
  const [name, setName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [browserPath, setBrowserPath] = useState("");
  const [browserEntries, setBrowserEntries] = useState<FsBrowseEntry[]>([]);
  const [browserTruncated, setBrowserTruncated] = useState(false);
  const [browserLoading, setBrowserLoading] = useState(false);
  const [browserError, setBrowserError] = useState<string | null>(null);

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

  async function browse(path: string) {
    setBrowserLoading(true);
    setBrowserError(null);
    try {
      const result = await browseFilesystem(path);
      setBrowserPath(result.path);
      setLocalPath(result.path);
      setBrowserEntries(result.items);
      setBrowserTruncated(result.truncated);
    } catch (caught) {
      setBrowserError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBrowserLoading(false);
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
      <Panel title="Folder Browser">
        <div className="browser-controls">
          <Field label="Path">
            <input
              value={localPath}
              onChange={(event) => setLocalPath(event.target.value)}
              placeholder="Enter a registered repo path"
            />
          </Field>
          <button type="button" className="secondary" onClick={() => browse(localPath)} disabled={browserLoading}>
            {browserLoading ? "Browsing" : "Browse"}
          </button>
        </div>
        <ErrorBanner message={browserError} />
        {browserLoading ? <Loading label="Browsing" /> : null}
        {!browserLoading && browserEntries.length === 0 ? (
          <EmptyState>No directory entries loaded</EmptyState>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Kind</th>
                <th>Git repo</th>
                <th>Path</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {browserEntries.map((entry) => (
                <tr key={entry.path}>
                  <td>{entry.name}</td>
                  <td>{entry.kind}</td>
                  <td>{entry.is_git_repo ? "Yes" : "No"}</td>
                  <td className="path-cell">{entry.path}</td>
                  <td>
                    {entry.kind === "directory" ? (
                      <div className="button-row">
                        <button type="button" className="secondary" onClick={() => browse(entry.path)}>
                          Open
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setLocalPath(entry.path);
                            setBrowserPath(entry.path);
                            if (entry.is_git_repo && !name) {
                              setName(entry.name);
                            }
                          }}
                        >
                          Use
                        </button>
                      </div>
                    ) : (
                      "None"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {browserTruncated ? <div className="notice">Showing the first entries only</div> : null}
        <div className="subtle path-cell">Current browser path: {browserPath}</div>
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
