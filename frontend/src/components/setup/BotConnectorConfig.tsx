import { useState, useEffect, useCallback } from "react";
import {
  fetchBotConfigs,
  createBotConfig,
  updateBotConfig,
  deleteBotConfig,
  type BotConfig,
  type ConnectorType,
} from "../../lib/api";

interface Props {
  projectId: number;
}

const CONNECTOR_OPTIONS: { value: ConnectorType; label: string; description: string }[] = [
  { value: "glean", label: "Glean", description: "Glean conversational search API" },
  { value: "openai", label: "OpenAI", description: "GPT models via OpenAI API" },
  { value: "claude", label: "Claude", description: "Anthropic Claude models" },
  { value: "deepseek", label: "DeepSeek", description: "DeepSeek chat models" },
  { value: "gemini", label: "Gemini", description: "Google Gemini models" },
  { value: "custom", label: "Custom API", description: "Any HTTP endpoint" },
];

const DEFAULT_MODELS: Partial<Record<ConnectorType, string>> = {
  openai: "gpt-4o-mini",
  claude: "claude-sonnet-4-20250514",
  deepseek: "deepseek-chat",
  gemini: "gemini-2.0-flash",
};

export default function BotConnectorConfig({ projectId }: Props) {
  const [configs, setConfigs] = useState<BotConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Form state
  const [selectedType, setSelectedType] = useState<ConnectorType>("glean");
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptForSources, setPromptForSources] = useState(false);
  // Glean-specific
  const [agentId, setAgentId] = useState("");
  // Custom connector fields
  const [endpointUrl, setEndpointUrl] = useState("");
  const [headersJson, setHeadersJson] = useState("");
  const [requestBodyTemplate, setRequestBodyTemplate] = useState('{"question": "{{question}}"}');
  const [responseAnswerPath, setResponseAnswerPath] = useState("$.answer");

  const [editingId, setEditingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchBotConfigs(projectId);
      setConfigs(data);
    } catch {
      // no configs yet
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  function resetForm() {
    setName("");
    setApiKey("");
    setBaseUrl("");
    setModel("");
    setSystemPrompt("");
    setPromptForSources(false);
    setAgentId("");
    setEndpointUrl("");
    setHeadersJson("");
    setRequestBodyTemplate('{"question": "{{question}}"}');
    setResponseAnswerPath("$.answer");
    setEditingId(null);
    setConfirmDelete(false);
  }

  function handleTypeChange(type: ConnectorType) {
    setSelectedType(type);
    setModel(DEFAULT_MODELS[type] ?? "");
    if (!editingId) {
      setApiKey("");
      setBaseUrl("");
      setSystemPrompt("");
      setEndpointUrl("");
      setHeadersJson("");
    }
  }

  function populateFormFromConfig(cfg: BotConfig) {
    setEditingId(cfg.id);
    setSelectedType(cfg.connector_type);
    setName(cfg.name);
    setPromptForSources(cfg.prompt_for_sources);
    const c = cfg.config_json as Record<string, string>;
    setApiKey(c.api_key ?? "");
    setBaseUrl(c.base_url ?? "");
    setModel(c.model ?? DEFAULT_MODELS[cfg.connector_type] ?? "");
    setSystemPrompt(c.system_prompt ?? "");
    setAgentId(c.agent_id ?? "");
    setEndpointUrl(c.endpoint_url ?? "");
    setHeadersJson(c.headers ? JSON.stringify(c.headers, null, 2) : "");
    setRequestBodyTemplate(c.request_body_template ?? '{"question": "{{question}}"}');
    setResponseAnswerPath(c.response_answer_path ?? "$.answer");
  }

  function buildConfigJson(): Record<string, unknown> {
    if (selectedType === "glean") {
      const cfg: Record<string, unknown> = { api_key: apiKey };
      if (baseUrl.trim()) cfg.base_url = baseUrl.trim();
      if (agentId.trim()) cfg.agent_id = agentId.trim();
      return cfg;
    }
    if (selectedType === "custom") {
      const cfg: Record<string, unknown> = {
        endpoint_url: endpointUrl.trim(),
        request_body_template: requestBodyTemplate,
        response_answer_path: responseAnswerPath,
      };
      if (headersJson.trim()) {
        try {
          cfg.headers = JSON.parse(headersJson);
        } catch {
          throw new Error("Custom headers must be valid JSON");
        }
      }
      return cfg;
    }
    // LLM connectors: openai, claude, deepseek, gemini
    const cfg: Record<string, unknown> = { api_key: apiKey };
    if (model.trim()) cfg.model = model.trim();
    if (systemPrompt.trim()) cfg.system_prompt = systemPrompt.trim();
    return cfg;
  }

  async function handleSave() {
    setError(null);
    setSuccess(null);

    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Bot name is required.");
      return;
    }
    if (!apiKey.trim() && selectedType !== "custom") {
      setError("API key is required.");
      return;
    }
    if (selectedType === "custom" && !endpointUrl.trim()) {
      setError("Endpoint URL is required.");
      return;
    }

    let configJson: Record<string, unknown>;
    try {
      configJson = buildConfigJson();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid config");
      return;
    }

    setSaving(true);
    try {
      if (editingId) {
        await updateBotConfig(projectId, editingId, {
          name: trimmedName,
          connector_type: selectedType,
          config_json: configJson,
          prompt_for_sources: promptForSources,
        });
        setSuccess("Bot config updated.");
      } else {
        await createBotConfig(projectId, {
          name: trimmedName,
          connector_type: selectedType,
          config_json: configJson,
          prompt_for_sources: promptForSources,
        });
        setSuccess("Bot config saved.");
      }
      resetForm();
      await load();
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!editingId) return;
    try {
      await deleteBotConfig(projectId, editingId);
      setSuccess("Bot config removed.");
      resetForm();
      await load();
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    }
  }

  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="mb-3 text-sm font-semibold text-text-primary">Bot Connector</h3>
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

  const isLLMType = ["openai", "claude", "deepseek", "gemini"].includes(selectedType);

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="mb-1 text-sm font-semibold text-text-primary">Bot Connector</h3>
      <p className="mb-4 text-xs text-text-secondary">
        Configure an external bot to test against your evaluation pipeline.
      </p>

      {/* Existing configs */}
      {configs.length > 0 && (
        <div className="mb-4 space-y-2">
          <label className="block text-xs font-medium text-text-secondary">Saved Configs</label>
          {configs.map((cfg) => (
            <button
              key={cfg.id}
              onClick={() => populateFormFromConfig(cfg)}
              className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                editingId === cfg.id
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border bg-surface text-text-primary hover:border-border-focus"
              }`}
            >
              <div>
                <span className="font-medium">{cfg.name}</span>
                <span className="ml-2 rounded bg-surface-elevated px-1.5 py-0.5 text-xs text-text-muted">
                  {cfg.connector_type}
                </span>
              </div>
              <svg className="h-3.5 w-3.5 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
              </svg>
            </button>
          ))}
          {editingId && (
            <button
              onClick={resetForm}
              className="text-xs text-accent hover:underline"
            >
              + New config
            </button>
          )}
        </div>
      )}

      {/* Connector type radio buttons */}
      <div className="mb-4">
        <label className="mb-2 block text-xs font-medium text-text-secondary">Connector Type</label>
        <div className="grid grid-cols-2 gap-2">
          {CONNECTOR_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 transition-colors ${
                selectedType === opt.value
                  ? "border-accent bg-accent/8"
                  : "border-border bg-surface hover:border-border-focus"
              }`}
            >
              <input
                type="radio"
                name="connector_type"
                value={opt.value}
                checked={selectedType === opt.value}
                onChange={() => handleTypeChange(opt.value)}
                className="mt-0.5 accent-accent"
              />
              <div>
                <div className="text-sm font-medium text-text-primary">{opt.label}</div>
                <div className="text-xs text-text-muted">{opt.description}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Config fields */}
      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Name <span className="text-score-low">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={`My ${CONNECTOR_OPTIONS.find((o) => o.value === selectedType)?.label} Bot`}
            className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
          />
        </div>

        {/* API Key — all except custom */}
        {selectedType !== "custom" && (
          <div>
            <label className="mb-1 block text-xs font-medium text-text-secondary">
              API Key <span className="text-score-low">*</span>
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={selectedType === "glean" ? "Glean API token" : "sk-..."}
              className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
            />
          </div>
        )}

        {/* Glean-specific: base URL + agent ID */}
        {selectedType === "glean" && (
          <>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Base URL <span className="text-text-muted">(optional)</span>
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://your-company-be.glean.com"
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Agent ID <span className="text-text-muted">(optional)</span>
              </label>
              <input
                type="text"
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                placeholder="e.g. 12345 — leave blank to use default Glean chat"
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
              />
              <p className="mt-1 text-xs text-text-muted">
                Specify a Glean Assistant/Agent ID to route questions to a specific agent instead of the default bot.
              </p>
            </div>
          </>
        )}

        {/* LLM connectors: model + system prompt */}
        {isLLMType && (
          <>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Model <span className="text-text-muted">(optional)</span>
              </label>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={DEFAULT_MODELS[selectedType] ?? ""}
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                System Prompt <span className="text-text-muted">(optional)</span>
              </label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="You are a helpful assistant..."
                rows={2}
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
              />
            </div>
          </>
        )}

        {/* Custom connector fields */}
        {selectedType === "custom" && (
          <>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Endpoint URL <span className="text-score-low">*</span>
              </label>
              <input
                type="text"
                value={endpointUrl}
                onChange={(e) => setEndpointUrl(e.target.value)}
                placeholder="https://api.example.com/chat"
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
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Request Body Template
              </label>
              <input
                type="text"
                value={requestBodyTemplate}
                onChange={(e) => setRequestBodyTemplate(e.target.value)}
                placeholder='{"question": "{{question}}"}'
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm font-mono text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Response Answer JSONPath
              </label>
              <input
                type="text"
                value={responseAnswerPath}
                onChange={(e) => setResponseAnswerPath(e.target.value)}
                placeholder="$.answer"
                className="w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm font-mono text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none"
              />
            </div>
          </>
        )}

        {/* Prompt for sources toggle — LLM types only */}
        {isLLMType && (
          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={promptForSources}
              onChange={(e) => setPromptForSources(e.target.checked)}
              className="accent-accent"
            />
            Ask bot to cite sources
          </label>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/80 disabled:opacity-50"
          >
            {saving ? "Saving..." : editingId ? "Update" : "Save"}
          </button>

          {editingId && !confirmDelete && (
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
