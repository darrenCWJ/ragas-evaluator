import { useState, useRef, useEffect } from "react";
import type { ChunkConfig, TestSetCreate } from "../../lib/api";
import { createTestSet, ApiError } from "../../lib/api";

const GENERATION_TIMEOUT_MS = 45 * 60 * 1000; // 45 minutes (large test sets need many LLM calls)

const QUERY_TYPES = [
  { key: "single_hop_specific", label: "Single-hop Specific", description: "Direct factual questions answerable from a single chunk (e.g. \"What is the default timeout?\")" },
  { key: "multi_hop_abstract", label: "Multi-hop Abstract", description: "High-level questions requiring synthesis across multiple chunks (e.g. \"How does the system handle errors?\")" },
  { key: "multi_hop_specific", label: "Multi-hop Specific", description: "Precise questions needing details from multiple chunks (e.g. \"Which config options affect both caching and logging?\")" },
] as const;

const QUESTION_CATEGORIES = [
  { key: "typical", label: "Typical", description: "Common, expected queries users would ask in normal scenarios" },
  { key: "in_knowledge_base", label: "In Knowledge Base", description: "Questions about content within the knowledge base" },
  { key: "edge", label: "Edge", description: "Questions in unusual or challenging scenarios" },
  { key: "out_of_knowledge_base", label: "Out of Knowledge Base", description: "Questions about content outside the knowledge base" },
] as const;

const DEFAULT_CATEGORIES: Record<string, number> = {
  typical: 30,
  in_knowledge_base: 30,
  edge: 20,
  out_of_knowledge_base: 20,
};

const DEFAULT_DISTRIBUTION: Record<string, number> = {
  single_hop_specific: 50,
  multi_hop_abstract: 25,
  multi_hop_specific: 25,
};

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
  const [testsetSize, setTestsetSize] = useState<string>("10");
  const [numPersonas, setNumPersonas] = useState<string>("3");
  const [usePersonas, setUsePersonas] = useState(true);
  const [customPersonas, setCustomPersonas] = useState<
    { name: string; role_description: string }[]
  >([]);
  const [chunkSampleSize, setChunkSampleSize] = useState<string>("100");
  const [numWorkers, setNumWorkers] = useState(4);
  const [queryDistribution, setQueryDistribution] = useState<Record<string, number>>({ ...DEFAULT_DISTRIBUTION });
  const [useCustomDistribution, setUseCustomDistribution] = useState(false);
  const [useCategories, setUseCategories] = useState(false);
  const [enabledCategories, setEnabledCategories] = useState<Record<string, boolean>>({
    typical: true,
    in_knowledge_base: true,
    edge: true,
    out_of_knowledge_base: true,
  });
  const [categoryDistribution, setCategoryDistribution] = useState<Record<string, number>>({ ...DEFAULT_CATEGORIES });
  const [generating, setGenerating] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [sizeError, setSizeError] = useState<string | null>(null);
  const [personasError, setPersonasError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!generating) {
      setElapsed(0);
      return;
    }
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [generating]);

  const validateSize = (s: string) => {
    const v = Number(s);
    if (!s || v < 1 || v > 400) {
      setSizeError("Must be between 1 and 400");
      return false;
    }
    setSizeError(null);
    return true;
  };

  const validatePersonas = (s: string) => {
    const v = Number(s);
    if (!s || v < 1 || v > 10) {
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

    const parsedSize = Number(testsetSize);
    const parsedPersonas = Number(numPersonas);
    const parsedChunkSample = Number(chunkSampleSize) || 0;

    const controller = new AbortController();
    abortRef.current = controller;
    const timeout = setTimeout(() => controller.abort(), GENERATION_TIMEOUT_MS);

    setGenerating(true);
    try {
      const config: TestSetCreate = {
        chunk_config_id: chunkConfigId as number,
        testset_size: parsedSize,
        num_personas: usePersonas ? parsedPersonas : undefined,
        use_personas: usePersonas,
        query_distribution: useCustomDistribution
          ? Object.fromEntries(
              Object.entries(queryDistribution).map(([k, v]) => [k, v / 100]),
            )
          : undefined,
        chunk_sample_size: parsedChunkSample,
        num_workers: numWorkers,
      };
      if (name.trim()) config.name = name.trim();

      // Include question categories if enabled
      if (useCategories) {
        const activeCats: Record<string, number> = {};
        for (const cat of QUESTION_CATEGORIES) {
          if (enabledCategories[cat.key]) {
            activeCats[cat.key] = categoryDistribution[cat.key] ?? 0;
          }
        }
        if (Object.keys(activeCats).length > 0) {
          config.question_categories = activeCats;
        }
      }

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
      setTestsetSize("10");
      setNumPersonas("3");
      setUsePersonas(true);
      setCustomPersonas([]);
      setChunkSampleSize("100");
      setNumWorkers(4);
      setUseCustomDistribution(false);
      setQueryDistribution({ ...DEFAULT_DISTRIBUTION });
      setUseCategories(false);
      setEnabledCategories({ typical: true, in_knowledge_base: true, edge: true, out_of_knowledge_base: true });
      setCategoryDistribution({ ...DEFAULT_CATEGORIES });
      onTestSetCreated();
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        setError(
          "Generation timed out — try a smaller test set size or fewer personas.",
        );
      } else if (err instanceof ApiError) {
        if (err.status === 422) {
          setError(err.message || "No chunks found for this config. Generate chunks in the Build stage first.");
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

  if (generating) {
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    const timeStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

    const steps = [
      { label: "Extracting summaries from chunks", threshold: 0 },
      { label: "Building embeddings", threshold: 30 },
      { label: "Extracting themes & entities", threshold: 60 },
      { label: "Building knowledge graph relationships", threshold: 90 },
      { label: "Generating personas", threshold: 120 },
      { label: "Synthesizing questions", threshold: 150 },
    ];
    let activeIdx = 0;
    for (let i = steps.length - 1; i >= 0; i--) {
      if (elapsed >= (steps[i]?.threshold ?? 0)) { activeIdx = i; break; }
    }

    return (
      <div className="space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Generate Test Set
        </h3>
        <div className="flex flex-col items-center gap-5 rounded-lg border border-border bg-elevated/50 py-10 px-6">
          {/* Spinner */}
          <svg className="h-10 w-10 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>

          <div className="text-center">
            <p className="text-sm font-medium text-text-primary">Generating test set…</p>
            <p className="mt-1 text-xs tabular-nums text-text-muted">Elapsed: {timeStr}</p>
          </div>

          {/* Steps */}
          <div className="w-full max-w-xs space-y-2">
            {steps.map((step, i) => (
              <div key={i} className="flex items-center gap-2">
                {i < activeIdx ? (
                  <svg className="h-4 w-4 shrink-0 text-score-high" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : i === activeIdx ? (
                  <svg className="h-4 w-4 shrink-0 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <div className="h-4 w-4 shrink-0 rounded-full border border-border" />
                )}
                <span className={`text-xs ${i <= activeIdx ? "text-text-secondary" : "text-text-muted"}`}>
                  {step.label}
                </span>
              </div>
            ))}
          </div>

          <p className="text-xs text-text-muted">This may take a few minutes depending on chunk count.</p>
        </div>
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
            max={400}
            value={testsetSize}
            onChange={(e) => {
              setTestsetSize(e.target.value);
              validateSize(e.target.value);
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

        {/* Chunk sample size */}
        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Chunk Sample Size
          </label>
          <input
            type="number"
            min={0}
            value={chunkSampleSize}
            onChange={(e) => setChunkSampleSize(e.target.value)}
            className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent"
            disabled={generating}
          />
          <p className="mt-1 text-xs text-text-muted">
            Random subset of chunks to use. 0 = all chunks.
          </p>
        </div>

        {/* Parallel workers */}
        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">
            Parallel Workers
          </label>
          <select
            value={numWorkers}
            onChange={(e) => setNumWorkers(Number(e.target.value))}
            className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent"
            disabled={generating}
          >
            {[1, 2, 4, 6, 8].map((n) => (
              <option key={n} value={n}>
                {n} {n === 1 ? "worker" : "workers"}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-text-muted">
            More workers = faster generation. Increase for large test sets.
          </p>
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
                setNumPersonas(e.target.value);
                validatePersonas(e.target.value);
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
              disabled={generating || customPersonas.length >= (Number(numPersonas) || 1)}
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-muted transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              + Add Persona
              {customPersonas.length >= (Number(numPersonas) || 1) && (
                <span className="ml-1 text-text-muted">
                  (max {numPersonas})
                </span>
              )}
            </button>
          </div>
        )}
        {/* Question categories toggle */}
        <div className="sm:col-span-2 flex items-end gap-3 pb-1">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={useCategories}
              onChange={(e) => setUseCategories(e.target.checked)}
              className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
              disabled={generating}
            />
            Question Categories
          </label>
        </div>

        {/* Question categories config */}
        {useCategories && (
          <div className="sm:col-span-2 space-y-3 rounded-lg border border-border bg-elevated/50 p-3">
            <p className="text-xs text-text-muted">
              Select which question categories to include and adjust their proportions.
            </p>
            {QUESTION_CATEGORIES.map((cat) => {
              const enabled = enabledCategories[cat.key] ?? false;
              const pct = categoryDistribution[cat.key] ?? 0;
              return (
                <div key={cat.key} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(e) => {
                          const next = { ...enabledCategories, [cat.key]: e.target.checked };
                          setEnabledCategories(next);
                          // Redistribute percentages among enabled categories
                          const enabledKeys = QUESTION_CATEGORIES
                            .map((c) => c.key)
                            .filter((k) => next[k]);
                          if (enabledKeys.length > 0) {
                            const share = Math.round(100 / enabledKeys.length);
                            const newDist: Record<string, number> = {};
                            enabledKeys.forEach((k, i) => {
                              newDist[k] = i === enabledKeys.length - 1
                                ? 100 - share * (enabledKeys.length - 1)
                                : share;
                            });
                            QUESTION_CATEGORIES.forEach((c) => {
                              if (!next[c.key]) newDist[c.key] = 0;
                            });
                            setCategoryDistribution(newDist);
                          }
                        }}
                        className="h-3.5 w-3.5 rounded border-border bg-input text-accent accent-accent"
                        disabled={generating}
                      />
                      <div>
                        <label className="text-xs font-medium text-text-secondary">
                          {cat.label}
                        </label>
                        <p className="text-[11px] leading-tight text-text-muted">{cat.description}</p>
                      </div>
                    </div>
                    {enabled && (
                      <div className="flex shrink-0 items-baseline gap-0.5">
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={pct}
                          onFocus={(e) => e.target.select()}
                          onChange={(e) => {
                            const raw = Math.max(0, Math.min(100, Number(e.target.value) || 0));
                            setCategoryDistribution((prev) => {
                              const enabledKeys = QUESTION_CATEGORIES
                                .map((c) => c.key)
                                .filter((k) => enabledCategories[k] && k !== cat.key);
                              const otherTotal = enabledKeys.reduce(
                                (sum, k) => sum + (prev[k] ?? 0),
                                0,
                              );
                              const remaining = 100 - raw;
                              const next: Record<string, number> = { ...prev, [cat.key]: raw };
                              if (otherTotal === 0) {
                                const share = Math.round(remaining / enabledKeys.length);
                                enabledKeys.forEach((k, i) => {
                                  next[k] = i === enabledKeys.length - 1
                                    ? remaining - share * (enabledKeys.length - 1)
                                    : share;
                                });
                              } else {
                                let allocated = 0;
                                enabledKeys.forEach((k, i) => {
                                  if (i === enabledKeys.length - 1) {
                                    next[k] = remaining - allocated;
                                  } else {
                                    const share = Math.round(((prev[k] ?? 0) / otherTotal) * remaining);
                                    next[k] = share;
                                    allocated += share;
                                  }
                                });
                              }
                              return next;
                            });
                          }}
                          disabled={generating}
                          className="w-10 rounded border border-border bg-input px-1 py-0.5 text-right text-xs tabular-nums text-text-primary focus:border-accent focus:outline-none"
                        />
                        <span className="text-xs text-text-muted">%</span>
                      </div>
                    )}
                  </div>
                  {enabled && (
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={pct}
                      onChange={(e) => {
                        const raw = Number(e.target.value);
                        setCategoryDistribution((prev) => {
                          const enabledKeys = QUESTION_CATEGORIES
                            .map((c) => c.key)
                            .filter((k) => enabledCategories[k] && k !== cat.key);
                          const otherTotal = enabledKeys.reduce(
                            (sum, k) => sum + (prev[k] ?? 0),
                            0,
                          );
                          const remaining = 100 - raw;
                          const next: Record<string, number> = { ...prev, [cat.key]: raw };
                          if (otherTotal === 0) {
                            const share = Math.round(remaining / enabledKeys.length);
                            enabledKeys.forEach((k, i) => {
                              next[k] = i === enabledKeys.length - 1
                                ? remaining - share * (enabledKeys.length - 1)
                                : share;
                            });
                          } else {
                            let allocated = 0;
                            enabledKeys.forEach((k, i) => {
                              if (i === enabledKeys.length - 1) {
                                next[k] = remaining - allocated;
                              } else {
                                const share = Math.round(((prev[k] ?? 0) / otherTotal) * remaining);
                                next[k] = share;
                                allocated += share;
                              }
                            });
                          }
                          return next;
                        });
                      }}
                      className="w-full accent-accent"
                      disabled={generating}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Query distribution toggle */}
        <div className="sm:col-span-2 flex items-end gap-3 pb-1">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={useCustomDistribution}
              onChange={(e) => setUseCustomDistribution(e.target.checked)}
              className="h-4 w-4 rounded border-border bg-input text-accent accent-accent"
              disabled={generating}
            />
            Custom Query Distribution
          </label>
        </div>

        {/* Query distribution sliders */}
        {useCustomDistribution && (
          <div className="sm:col-span-2 space-y-3 rounded-lg border border-border bg-elevated/50 p-3">
            <p className="text-xs text-text-muted">
              Adjust the proportion of each question type. Values always sum to 100%.
            </p>
            {QUERY_TYPES.map((qt) => {
              const pct = queryDistribution[qt.key] ?? 0;
              return (
                <div key={qt.key} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <div>
                      <label className="text-xs font-medium text-text-secondary">
                        {qt.label}
                      </label>
                      <p className="text-[11px] leading-tight text-text-muted">{qt.description}</p>
                    </div>
                    <div className="flex shrink-0 items-baseline gap-0.5">
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={pct}
                        onFocus={(e) => e.target.select()}
                        onChange={(e) => {
                          const raw = Math.max(0, Math.min(100, Number(e.target.value) || 0));
                          setQueryDistribution((prev) => {
                            const otherKeys = QUERY_TYPES
                              .map((q) => q.key)
                              .filter((k) => k !== qt.key);
                            const otherTotal = otherKeys.reduce(
                              (sum, k) => sum + (prev[k] ?? 0),
                              0,
                            );
                            const remaining = 100 - raw;
                            const next: Record<string, number> = { [qt.key]: raw };
                            if (otherTotal === 0) {
                              const share = Math.round(remaining / otherKeys.length);
                              otherKeys.forEach((k, i) => {
                                next[k] =
                                  i === otherKeys.length - 1
                                    ? remaining - share * (otherKeys.length - 1)
                                    : share;
                              });
                            } else {
                              let allocated = 0;
                              otherKeys.forEach((k, i) => {
                                if (i === otherKeys.length - 1) {
                                  next[k] = remaining - allocated;
                                } else {
                                  const share = Math.round(
                                    ((prev[k] ?? 0) / otherTotal) * remaining,
                                  );
                                  next[k] = share;
                                  allocated += share;
                                }
                              });
                            }
                            return next;
                          });
                        }}
                        disabled={generating}
                        className="w-10 rounded border border-border bg-input px-1 py-0.5 text-right text-xs tabular-nums text-text-primary focus:border-accent focus:outline-none"
                      />
                      <span className="text-xs text-text-muted">%</span>
                    </div>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={pct}
                    onChange={(e) => {
                      const raw = Number(e.target.value);
                      setQueryDistribution((prev) => {
                        const otherKeys = QUERY_TYPES
                          .map((q) => q.key)
                          .filter((k) => k !== qt.key);
                        const otherTotal = otherKeys.reduce(
                          (sum, k) => sum + (prev[k] ?? 0),
                          0,
                        );
                        const remaining = 100 - raw;
                        const next: Record<string, number> = { [qt.key]: raw };
                        if (otherTotal === 0) {
                          const share = Math.round(remaining / otherKeys.length);
                          otherKeys.forEach((k, i) => {
                            next[k] =
                              i === otherKeys.length - 1
                                ? remaining - share * (otherKeys.length - 1)
                                : share;
                          });
                        } else {
                          let allocated = 0;
                          otherKeys.forEach((k, i) => {
                            if (i === otherKeys.length - 1) {
                              next[k] = remaining - allocated;
                            } else {
                              const share = Math.round(
                                ((prev[k] ?? 0) / otherTotal) * remaining,
                              );
                              next[k] = share;
                              allocated += share;
                            }
                          });
                        }
                        return next;
                      });
                    }}
                    className="w-full accent-accent"
                    disabled={generating}
                  />
                </div>
              );
            })}
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
