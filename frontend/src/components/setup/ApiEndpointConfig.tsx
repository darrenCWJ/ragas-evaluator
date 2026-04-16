import { useState, useEffect, useCallback } from "react";
import { saveApiConfig, fetchApiConfig, deleteApiConfig, type ApiConfig } from "../../lib/api";

interface Props {
  projectId: number;
}

export default function ApiEndpointConfig({ projectId }: Props) {
  const [config, setConfig] = useState<ApiConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Form state
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [headersJson, setHeadersJson] = useState("");

  // Delete confirmation
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const cfg = await fetchApiConfig(projectId);
      setConfig(cfg);
      setUrl(cfg.endpoint_url);
      setApiKey(cfg.api_key ?? "");
      setHeadersJson(cfg.headers_json ?? "");
    } catch {
      // 404 = no config yet, that's fine
      setConfig(null);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave() {
    setError(null);
    setSuccess(null);

    const trimmed = url.trim();
    if (!trimmed) {
      setError("Endpoint URL is required.");
      return;
    }

    setSaving(true);
    try {
      const cfg = await saveApiConfig(projectId, {
        endpoint_url: trimmed,
        api_key: apiKey.trim() || null,
        headers_json: headersJson.trim() || null,
      });
      setConfig(cfg);
      setSuccess("API endpoint saved.");
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    try {
      await deleteApiConfig(projectId);
      setConfig(null);
      setUrl("");
      setApiKey("");
      setHeadersJson("");
      setConfirmDelete(false);
      setSuccess("API config removed.");
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    }
  }

  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-3 text-sm font-semibold text-text-primary">API Endpoint</h3>
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading...
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="mb-1 text-sm font-semibold text-text-primary">
        API Endpoint
      </h3>
      <p className="mb-4 text-xs text-text-secondary">
        Connect to an external API to fetch baseline Q&A data for evaluation.
      </p>

      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Endpoint URL <span className="text-score-low">*</span>
          </label>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://api.example.com/qa-pairs"
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            API Key <span className="text-text-muted">(optional)</span>
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Custom Headers <span className="text-text-muted">(optional JSON)</span>
          </label>
          <textarea
            value={headersJson}
            onChange={(e) => setHeadersJson(e.target.value)}
            placeholder='{"Authorization": "Bearer ...", "X-Custom": "value"}'
            rows={2}
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/80 disabled:opacity-50"
          >
            {saving ? "Saving..." : config ? "Update" : "Save"}
          </button>

          {config && !confirmDelete && (
            <button
              onClick={() => setConfirmDelete(true)}
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:border-score-low hover:text-score-low"
            >
              Remove
            </button>
          )}

          {confirmDelete && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">Delete config?</span>
              <button
                onClick={handleDelete}
                className="rounded-lg bg-score-low/15 px-3 py-1.5 text-xs font-medium text-score-low hover:bg-score-low/25"
              >
                Yes, delete
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>

      {success && (
        <div className="mt-3 rounded-lg bg-score-high/10 px-4 py-2 text-sm text-score-high">
          {success}
        </div>
      )}

      {error && (
        <div className="mt-3 rounded-lg bg-score-low/10 px-4 py-2 text-sm text-score-low">
          {error}
        </div>
      )}
    </div>
  );
}
