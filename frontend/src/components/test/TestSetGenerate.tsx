import { useState, useRef } from "react";
import type { ChunkConfig, TestSetCreate } from "../../lib/api";
import { createTestSet, ApiError } from "../../lib/api";

const GENERATION_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

interface Props {
  projectId: number;
  chunkConfigs: ChunkConfig[];
  onTestSetCreated: () => void;
}

export default function TestSetGenerate({
  projectId,
  chunkConfigs,
  onTestSetCreated,
}: Props) {
  const [chunkConfigId, setChunkConfigId] = useState<number | "">("");
  const [name, setName] = useState("");
  const [testsetSize, setTestsetSize] = useState(10);
  const [numPersonas, setNumPersonas] = useState(3);
  const [usePersonas, setUsePersonas] = useState(true);
  const [customPersonas, setCustomPersonas] = useState<
    { name: string; role_description: string }[]
  >([]);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sizeError, setSizeError] = useState<string | null>(null);
  const [personasError, setPersonasError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const validateSize = (v: number) => {
    if (v < 1 || v > 100) {
      setSizeError("Must be between 1 and 100");
      return false;
    }
    setSizeError(null);
    return true;
  };

  const validatePersonas = (v: number) => {
    if (v < 1 || v > 10) {
      setPersonasError("Must be between 1 and 10");
      return false;
    }
    setPersonasError(null);
    return true;
  };

  const handleGenerate = async () => {
    setError(null);
    const sizeOk = validateSize(testsetSize);
    const personasOk = !usePersonas || validatePersonas(numPersonas);
    if (!sizeOk || !personasOk || chunkConfigId === "") return;

    const controller = new AbortController();
    abortRef.current = controller;
    const timeout = setTimeout(() => controller.abort(), GENERATION_TIMEOUT_MS);

    setGenerating(true);
    try {
      const config: TestSetCreate = {
        chunk_config_id: chunkConfigId as number,
        testset_size: testsetSize,
        num_personas: usePersonas ? numPersonas : undefined,
        use_personas: usePersonas,
      };
      if (name.trim()) config.name = name.trim();

      // Include custom personas only if valid entries exist (both name and role_description required)
      if (usePersonas && customPersonas.length > 0) {
        const valid = customPersonas.filter(
          (p) => p.name.trim() && p.role_description.trim(),
        );
        if (valid.length > 0) {
          config.custom_personas = valid.map((p) => ({
            name: p.name.trim(),
            role_description: p.role_description.trim(),
          }));
        }
      }

      await createTestSet(projectId, config, controller.signal);
      setName("");
      setChunkConfigId("");
      setTestsetSize(10);
      setNumPersonas(3);
      setUsePersonas(true);
      setCustomPersonas([]);
      onTestSetCreated();
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        setError(
          "Generation timed out — try a smaller test set size or fewer personas.",
        );
      } else if (err instanceof ApiError) {
        if (err.status === 422) {
          setError("No chunks found for this config. Generate chunks in the Build stage first.");
        } else if (err.status === 429) {
          setError("Rate limit exceeded — wait a moment and try again.");
        } else {
          setError(err.message);
        }
      } else {
        setError((err as Error).message || "Generation failed");
      }
    } finally {
      clearTimeout(timeout);
      abortRef.current = null;
      setGenerating(false);
    }
  };

  if (chunkConfigs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card/50 p-8 text-center">
        <p className="text-sm text-text-muted">
          Create and generate chunks in the{" "}
          <span className="font-medium text-text-secondary">Build</span> stage
          first.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
        Generate Test Set
      </h3>

      <div className="grid gap-3 sm:grid-cols-2">
        {/* Chunk config selector */}
        <div className="sm:col-span-2">
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Chunk Config
          </label>
          <select
            value={chunkConfigId}
            onChange={(e) =>
              setChunkConfigId(e.target.value ? Number(e.target.value) : "")
            }
            className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
            disabled={generating}
          >
            <option value="">Select a chunk config…</option>
            {chunkConfigs.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.method})
              </option>
            ))}
          </select>
        </div>

        {/* Name */}
        <div className="sm:col-span-2">
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Name{" "}
            <span className="font-normal text-text-muted">(optional)</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Auto-generated if blank"
            className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            disabled={generating}
          />
        </div>

        {/* Test set size */}
        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Test Set Size
          </label>
          <input
            type="number"
            min={1}
            max={100}
            value={testsetSize}
            onChange={(e) => {
              const v = Number(e.target.value);
              setTestsetSize(v);
              validateSize(v);
            }}
            className={`w-full rounded-lg border px-3 py-2 text-sm text-text-primary focus:outline-none ${
              sizeError
                ? "border-red-500 focus:border-red-500"
                : "border-border bg-input focus:border-accent"
            }`}
            disabled={generating}
          />
          {sizeError && (
            <p className="mt-1 text-xs text-red-400">{sizeError}</p>
          )}
        </div>

        {/* Use personas toggle */}
        <div className="flex items-end gap-3 pb-1">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={usePersonas}
              onChange={(e) => setUsePersonas(e.target.checked)}
              className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
              disabled={generating}
            />
            Use Personas
          </label>
        </div>

        {/* Num personas */}
        {usePersonas && (
          <div>
            <label className="mb-1 block text-xs font-medium text-text-secondary">
              Number of Personas
            </label>
            <input
              type="number"
              min={1}
              max={10}
              value={numPersonas}
              onChange={(e) => {
                const v = Number(e.target.value);
                setNumPersonas(v);
                validatePersonas(v);
              }}
              className={`w-full rounded-lg border px-3 py-2 text-sm text-text-primary focus:outline-none ${
                personasError
                  ? "border-red-500 focus:border-red-500"
                  : "border-border bg-input focus:border-accent"
              }`}
              disabled={generating}
            />
            {personasError && (
              <p className="mt-1 text-xs text-red-400">{personasError}</p>
            )}
          </div>
        )}

        {/* Custom personas editor */}
        {usePersonas && (
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs font-medium text-text-secondary">
              Custom Personas{" "}
              <span className="font-normal text-text-muted">
                (optional — leave empty for auto-generated)
              </span>
            </label>

            {customPersonas.length > 0 && (
              <div className="mb-2 space-y-2">
                {customPersonas.map((p, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <input
                      type="text"
                      value={p.name}
                      onChange={(e) => {
                        setCustomPersonas((prev) =>
                          prev.map((item, j) =>
                            j === i ? { name: e.target.value, role_description: item.role_description } : item,
                          ),
                        );
                      }}
                      placeholder="Name"
                      className="w-1/3 rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                      disabled={generating}
                    />
                    <input
                      type="text"
                      value={p.role_description}
                      onChange={(e) => {
                        setCustomPersonas((prev) =>
                          prev.map((item, j) =>
                            j === i ? { name: item.name, role_description: e.target.value } : item,
                          ),
                        );
                      }}
                      placeholder="Role description"
                      className="flex-1 rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                      disabled={generating}
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setCustomPersonas(customPersonas.filter((_, j) => j !== i))
                      }
                      disabled={generating}
                      className="shrink-0 rounded-md border border-border p-1.5 text-text-muted transition hover:border-red-500/40 hover:text-red-400 disabled:opacity-40"
                      title="Remove persona"
                    >
                      <svg
                        className="h-3.5 w-3.5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M6 18 18 6M6 6l12 12"
                        />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}

            <button
              type="button"
              onClick={() =>
                setCustomPersonas([
                  ...customPersonas,
                  { name: "", role_description: "" },
                ])
              }
              disabled={generating || customPersonas.length >= numPersonas}
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-muted transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              + Add Persona
              {customPersonas.length >= numPersonas && (
                <span className="ml-1 text-text-muted">
                  (max {numPersonas})
                </span>
              )}
            </button>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Generate button */}
      <button
        onClick={handleGenerate}
        disabled={generating || chunkConfigId === ""}
        className="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition hover:bg-accent/80 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {generating ? (
          <span className="flex items-center gap-2">
            <svg
              className="h-4 w-4 animate-spin"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            Generating… this may take a few minutes
          </span>
        ) : (
          "Generate Test Set"
        )}
      </button>
    </div>
  );
}
