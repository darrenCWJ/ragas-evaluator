// Shared API types — all exported interfaces/types for the Ragas Platform backend, grouped by domain

// ---------------------------------------------------------------------------
// Projects, judge models, config defaults
// ---------------------------------------------------------------------------

export interface Project {
  id: number;
  name: string;
  description: string;
  created_at: string;
  judge_model_assignments: string[] | null;
  preferred_model?: string | null;
}

export interface JudgeModel {
  id: string;
  name: string;
  provider: 'openai' | 'anthropic' | 'gemini' | 'gateway';
  available: boolean;
}

export interface JudgeModelsResponse {
  models: JudgeModel[];
  default_model_assignments: string[] | null;
  temp_min: number;
  temp_max: number;
}

export interface ConfigDefaults {
  connector_types: string[];
  default_models: Record<string, string>;
  default_eval_model: string;
  default_eval_embedding: string;
}

// ---------------------------------------------------------------------------
// External baselines
// ---------------------------------------------------------------------------

export interface ExternalBaseline {
  id: number;
  project_id: number;
  question: string;
  answer: string;
  reference_answer: string;
  sources: string;
  source_type: string;
  created_at: string;
}

export interface CsvUploadResult {
  imported: number;
  bot_config_id: number;
  preview: { question: string; answer: string; sources: string }[];
}

export interface CsvPreviewResult {
  headers: string[];
  rows: Record<string, string>[];
}

// ---------------------------------------------------------------------------
// API configs
// ---------------------------------------------------------------------------

export interface ApiConfig {
  id: number;
  project_id: number;
  endpoint_url: string;
  api_key: string | null;
  headers_json: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiConfigCreate {
  endpoint_url: string;
  api_key?: string | null;
  headers_json?: string | null;
}

// ---------------------------------------------------------------------------
// Bot configs
// ---------------------------------------------------------------------------

export type ConnectorType =
  | 'glean'
  | 'openai'
  | 'claude'
  | 'deepseek'
  | 'gemini'
  | 'custom'
  | 'csv';

export interface BotConfig {
  id: number;
  project_id: number;
  name: string;
  connector_type: ConnectorType;
  config_json: Record<string, unknown>;
  prompt_for_sources: boolean;
  returns_contexts: boolean;
  created_at: string;
  updated_at: string;
}

export interface BotConfigCreatePayload {
  name: string;
  connector_type: ConnectorType;
  config_json: Record<string, unknown>;
  prompt_for_sources?: boolean;
}

export interface BotConfigBaselinesResult {
  total: number;
  rows: {
    id: number;
    question: string;
    answer: string;
    reference_answer: string;
    sources: string;
    created_at: string;
  }[];
}

// ---------------------------------------------------------------------------
// Project report
// ---------------------------------------------------------------------------

export interface ExperimentReportEntry {
  id: number;
  name: string;
  bot_config_id: number | null;
  bot_config_name: string | null;
  rag_config_id: number | null;
  rag_config_name: string | null;
  result_count: number;
  completed_at: string | null;
  aggregate_metrics: Record<string, number | null>;
  overall_score: number | null;
  source_verification: {
    verified: number;
    hallucinated: number;
    inaccessible: number;
    unverifiable: number;
    total: number;
    pct_verified: number;
    pct_hallucinated: number;
  } | null;
  evaluator_reliability: {
    total_annotations: number;
    scorable_count: number;
    agreements: number;
    agreement_rate: number;
  } | null;
}

export interface BotSummary {
  bot_config_id: number;
  bot_config_name: string | null;
  connector_type: string;
  experiment_count: number;
  total_results: number;
  aggregate_metrics: Record<string, number | null>;
  overall_score: number | null;
}

export interface ProjectReport {
  project_id: number;
  project_name: string;
  total_experiments: number;
  experiments: ExperimentReportEntry[];
  bot_summary: BotSummary[];
  overall_metrics: Record<string, number | null> | null;
  overall_source_verification: {
    verified: number;
    hallucinated: number;
    inaccessible: number;
    unverifiable: number;
    total: number;
    pct_verified: number;
    pct_hallucinated: number;
  } | null;
  overall_evaluator_reliability: {
    total_annotations: number;
    scorable_count: number;
    agreements: number;
    agreement_rate: number;
  } | null;
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export interface Document {
  id: number;
  filename: string;
  file_type: string;
  context_label: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Chunk configs
// ---------------------------------------------------------------------------

export interface ChunkConfig {
  id: number;
  project_id: number;
  name: string;
  method: string;
  params: Record<string, number | string>;
  step2_method: string | null;
  step2_params: Record<string, number | string> | null;
  filter_params: Record<string, number> | null;
  created_at: string;
}

export interface ChunkConfigCreate {
  name: string;
  method: string;
  params: Record<string, number | string>;
  step2_method?: string | null;
  step2_params?: Record<string, number | string> | null;
  filter_params?: Record<string, number> | null;
}

export interface ChunkPreviewResult {
  document_id: number;
  filename: string;
  chunks: string[];
  chunk_count: number;
}

export interface ChunkGenerateResult {
  total_chunks: number;
  skipped_documents: number;
  documents: { document_id: number; filename: string; chunk_count: number; skipped: boolean }[];
}

// ---------------------------------------------------------------------------
// Embedding configs
// ---------------------------------------------------------------------------

export interface EmbeddingConfig {
  id: number;
  project_id: number;
  name: string;
  type: string;
  model_name: string;
  params: Record<string, unknown> | null;
  created_at: string;
}

export interface EmbeddingConfigCreate {
  name: string;
  type: string;
  model_name: string;
  params?: Record<string, unknown> | null;
}

export interface EmbedResult {
  total_embedded: number;
  collection?: string;
  index?: string;
}

// ---------------------------------------------------------------------------
// RAG configs
// ---------------------------------------------------------------------------

export interface RagConfig {
  id: number;
  project_id: number;
  name: string;
  embedding_config_id: number;
  chunk_config_id: number;
  search_type: string;
  llm_model: string;
  top_k: number;
  system_prompt: string | null;
  llm_params: Record<string, unknown> | null;
  sparse_config_id: number | null;
  alpha: number | null;
  response_mode: string;
  max_steps: number | null;
  reranker_model: string | null;
  reranker_top_k: number | null;
  created_at: string;
}

export interface RagConfigCreate {
  name: string;
  embedding_config_id: number;
  chunk_config_id: number;
  search_type: string;
  llm_model: string;
  top_k?: number;
  system_prompt?: string | null;
  llm_params?: Record<string, unknown> | null;
  sparse_config_id?: number | null;
  alpha?: number | null;
  response_mode?: string;
  max_steps?: number | null;
  reranker_model?: string | null;
  reranker_top_k?: number | null;
}

export interface RagConfigExpanded extends RagConfig {
  chunk_config: { name: string; method: string; params: Record<string, number | string> } | null;
  embedding_config: { name: string; type: string; model_name: string } | null;
}

export interface RagQueryResult {
  answer: string;
  contexts: { content: string; chunk_id?: number; [key: string]: unknown }[];
  model: string;
  usage: { prompt_tokens: number; completion_tokens: number };
}

// ---------------------------------------------------------------------------
// Test sets, questions, generation, upload
// ---------------------------------------------------------------------------

export interface TestSet {
  id: number;
  name: string;
  project_id?: number;
  generation_config: {
    chunk_config_id: number;
    testset_size: number;
    num_personas: number;
    custom_personas: Record<string, unknown>[] | null;
    use_personas: boolean;
  };
  generation_status?: string;
  error_message?: string | null;
  created_at: string;
  total_questions: number;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
}

export interface TestSetCreate {
  chunk_config_id?: number;
  name?: string;
  testset_size?: number;
  num_personas?: number;
  custom_personas?: { name: string; role_description: string; question_style?: string }[];
  use_personas?: boolean;
  query_distribution?: Record<string, number>;
  chunk_sample_size?: number;
  num_workers?: number;
  question_categories?: Record<string, number>;
  graph_rag_kg_source?: string;
  use_kg_as_source?: boolean;
  fast_kg_mode?: boolean;
}

export interface TestQuestion {
  id: number;
  test_set_id: number;
  question: string;
  reference_answer: string;
  reference_contexts: string[];
  question_type: string;
  persona: string | null;
  category: string | null;
  status: string;
  user_edited_answer: string | null;
  user_edited_contexts: string[] | null;
  user_notes: string | null;
  metadata: Record<string, unknown> | null;
  reviewed_at: string | null;
}

export interface TestSetSummary {
  test_set_id: number;
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  edited: number;
  completion_pct: number;
}

export interface UploadPreviewResult {
  filename: string;
  total_rows: number;
  columns: string[];
  preview: Record<string, string>[];
}

export interface UploadConfirmResult {
  id: number;
  name: string;
  project_id: number;
  question_count: number;
}

export interface GenerationProgress {
  active: boolean;
  stage?: string;
  questions_generated?: number;
  target_size?: number;
  status?: 'generating' | 'completed' | 'failed' | 'cancelled';
  test_set_id?: number;
  error_message?: string;
}

export interface CreateTestSetResponse {
  id: number;
  name: string;
  project_id: number;
  status: 'generating';
}

// ---------------------------------------------------------------------------
// Insights — test set quality audit, corpus coverage, category breakdown
// ---------------------------------------------------------------------------

/** Per-question audit result stored at `TestQuestion.metadata.quality`. */
export interface QuestionQuality {
  score: number;
  flags: string[];
  reasoning: string;
}

export interface QualityAuditSummary {
  audited: number;
  avg_score: number | null;
  flag_counts: Record<string, number>;
  flagged_question_ids: number[];
  use_llm: boolean;
}

export interface CoverageDocument {
  document_id: number;
  filename: string;
  question_count: number;
  covered: boolean;
}

export interface CoverageReport {
  total_questions: number;
  questions_with_provenance: number;
  total_documents: number;
  covered_documents: number;
  uncovered_documents: string[];
  total_chunks: number;
  covered_chunks: number;
  chunk_coverage: number | null;
  documents: CoverageDocument[];
}

export interface WeakestQuestion {
  question_id: number;
  question: string;
  mean_score: number | null;
}

export interface CategoryBreakdown {
  category: string;
  question_count: number;
  overall: number | null;
  metrics: Record<string, number>;
  weakest_questions: WeakestQuestion[];
}

export interface ExperimentBreakdown {
  categories: CategoryBreakdown[];
}

// ---------------------------------------------------------------------------
// Personas
// ---------------------------------------------------------------------------

export interface SavedPersona {
  id: number;
  name: string;
  role_description: string;
  question_style: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Annotations (test set question review + human annotation of experiments)
// ---------------------------------------------------------------------------

export interface QuestionAnnotation {
  status: 'approved' | 'rejected' | 'edited';
  user_edited_answer?: string;
  user_edited_contexts?: string[];
  user_notes?: string;
  metadata?: Record<string, unknown>;
}

export interface BulkAnnotation {
  action: 'approve' | 'reject' | 'approve_all' | 'reject_all';
  question_ids?: number[];
}

export interface BulkAnnotationResult {
  updated_count: number;
}

export interface AnnotationSampleItem {
  experiment_result_id: number;
  test_question_id: number;
  question: string;
  reference_answer: string;
  response: string | null;
  metrics: Record<string, number>;
  annotation: {
    rating: string;
    notes: string | null;
    annotated_at: string;
  } | null;
}

export interface AnnotationSampleResult {
  experiment_id: number;
  total_results: number;
  sample_size: number;
  annotated_count: number;
  sample: AnnotationSampleItem[];
}

export interface HumanAnnotationCreate {
  experiment_result_id: number;
  rating: 'accurate' | 'partially_accurate' | 'inaccurate';
  notes?: string | null;
}

export interface EvaluatorAccuracyComparison {
  experiment_result_id: number;
  question: string;
  response: string | null;
  reference_answer: string;
  human_rating: string;
  human_score: number;
  evaluator_score: number | null;
  evaluator_rating: string | null;
  agrees: boolean | null;
  notes: string | null;
}

export interface EvaluatorAccuracyResult {
  experiment_id: number;
  total_annotations: number;
  scorable_count: number;
  agreements: number;
  agreement_rate: number | null;
  comparisons: EvaluatorAccuracyComparison[];
}

// ---------------------------------------------------------------------------
// Experiments
// ---------------------------------------------------------------------------

export interface Experiment {
  id: number;
  project_id: number;
  test_set_id: number;
  name: string;
  model: string;
  model_params: Record<string, unknown> | null;
  retrieval_config: Record<string, unknown> | null;
  chunk_config_id: number;
  embedding_config_id: number;
  rag_config_id: number;
  bot_config_id: number | null;
  baseline_experiment_id: number | null;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  // Optional aggregate fields (present on GET single / list)
  test_set_name?: string;
  rag_config_name?: string;
  has_reference_contexts?: boolean;
  has_reference_sql?: boolean;
  has_reference_data?: boolean;
  connector_type?: string | null;
  bot_returns_contexts?: boolean;
  approved_question_count?: number;
  result_count?: number;
  aggregate_metrics?: Record<string, number | null> | null;
}

export interface ExperimentCreate {
  test_set_id?: number | null;
  rag_config_id?: number | null;
  bot_config_id?: number | null;
  name: string;
}

export interface ExperimentResult {
  id: number;
  test_question_id: number;
  question: string;
  reference_answer: string;
  question_type: string;
  persona: string | null;
  response: string | null;
  retrieved_contexts: { content: string; chunk_id?: number }[];
  metrics: Record<string, number>;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface ProgressSnapshot {
  phase: string;
  current: number;
  total: number;
  question: string;
  in_flight: string[];
  in_flight_details: InFlightDetail[];
  scoring_metrics: string[];
  error: string | null;
  result_count: number;
}

// --- Experiment SSE events ---

export interface SSEStartedEvent {
  experiment_id: number;
  total_questions: number;
  metrics: string[];
  experiment_name?: string;
  model?: string;
  test_set_name?: string;
}

export interface SSECompletionItem {
  question: string;
  response: string | null;
  error: string | null;
  metrics?: Record<string, number | null>;
}

export interface InFlightDetail {
  question: string;
  phase: 'querying' | 'scoring';
  metrics_done: string[];
  metrics_active: string[];
  metrics_pending: string[];
}

export interface SSEProgressEvent {
  current: number;
  total: number;
  question_id: number;
  question: string;
  error?: string;
  in_flight?: string[];
  new_completions?: SSECompletionItem[];
  scoring_metrics?: string[];
  in_flight_details?: InFlightDetail[];
}

export interface SSECompletedEvent {
  experiment_id: number;
  result_count: number;
}

export interface SSEErrorEvent {
  message: string;
}

export interface ExperimentSSECallbacks {
  onStarted?: (data: SSEStartedEvent) => void;
  onProgress?: (data: SSEProgressEvent) => void;
  onCompleted?: (data: SSECompletedEvent) => void;
  onError?: (data: SSEErrorEvent) => void;
  onConnectionError?: (error: Error, lastProgress: SSEProgressEvent | null) => void;
}

export interface ExperimentSSEHandle {
  abort: () => void;
}

// --- Suggestions ---

export interface Suggestion {
  id: number;
  experiment_id: number;
  category: string;
  signal: string;
  suggestion: string;
  priority: 'high' | 'medium' | 'low';
  config_field: string | null;
  suggested_value: string | null;
  implemented: boolean;
  created_at: string;
}

export interface BatchApplyResult {
  suggestions: Suggestion[];
  new_experiment: Experiment;
  new_rag_config: { id: number; name: string };
  changes: Record<string, { old: unknown; new: unknown }>;
}

// --- Delta ---

export interface ConfigChange {
  field: string;
  old_value: unknown;
  new_value: unknown;
}

export interface MetricDelta {
  baseline: number | null;
  iteration: number | null;
  delta: number | null;
  improved: boolean | null;
}

export interface QuestionDelta {
  test_question_id: number;
  question: string | null;
  metrics: Record<
    string,
    { baseline: number | null; iteration: number | null; delta: number | null }
  >;
}

export interface DeltaResult {
  experiment_id: number;
  experiment_name: string;
  baseline_experiment_id: number;
  baseline_experiment_name: string;
  config_changes: ConfigChange[];
  metric_deltas: Record<string, MetricDelta>;
  per_question_deltas: QuestionDelta[];
}

// --- Comparison ---

export interface CompareQuestionExperimentData {
  response: string | null;
  metrics: Record<string, number>;
  retrieved_contexts: { content: string; chunk_id?: number }[];
  metadata: Record<string, unknown> | null;
}

export interface CompareQuestionData {
  test_question_id: number;
  question: string;
  reference_answer: string;
  question_type: string;
  persona: string | null;
  experiments: Record<number, CompareQuestionExperimentData>;
}

export interface CompareResult {
  experiments: Experiment[];
  questions: CompareQuestionData[];
}

// --- History ---

export interface HistoryExperiment extends Experiment {
  overall_score: number | null;
}

// --- Source verification ---

export interface SourceVerification {
  id: number;
  citation_index: number;
  title: string | null;
  url: string | null;
  status: 'verified' | 'hallucinated' | 'inaccessible' | 'unverifiable';
  details: string | null;
  created_at: string;
}

export interface SourceVerificationGroup {
  experiment_result_id: number;
  test_question_id: number;
  question: string;
  verifications: SourceVerification[];
}

export interface SourceVerificationResult {
  experiment_id: number;
  results: SourceVerificationGroup[];
}

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

export interface FewShotExample {
  question: string;
  response: string;
  verdict: string;
  reference?: string;
  score?: number;
  reasoning?: string;
}

export interface CustomMetric {
  id: number;
  project_id: number;
  name: string;
  metric_type:
    | 'integer_range'
    | 'similarity'
    | 'rubrics'
    | 'instance_rubrics'
    | 'criteria_judge'
    | 'reference_judge';
  prompt: string | null;
  rubrics: Record<string, string> | null;
  min_score: number;
  max_score: number;
  refined_prompt: string | null;
  few_shot_examples: FewShotExample[] | null;
  created_at: string;
}

export interface CustomMetricCreate {
  name: string;
  metric_type: string;
  prompt?: string | null;
  rubrics?: Record<string, string> | null;
  min_score?: number;
  max_score?: number;
  refined_prompt?: string | null;
  few_shot_examples?: FewShotExample[] | null;
}

// ---------------------------------------------------------------------------
// Multi-LLM judge
// ---------------------------------------------------------------------------

export interface JudgeClaim {
  type: 'praise' | 'critique';
  response_quote: string;
  chunk_reference: string | null;
  chunk_quote: string | null;
  explanation: string;
}

export interface ClaimAnnotation {
  status: 'accurate' | 'inaccurate' | 'unsure';
  comment: string | null;
  annotated_at: string;
}

export interface JudgeEvaluation {
  id: number;
  evaluator_index: number;
  verdict: 'positive' | 'mixed' | 'critical';
  score: number;
  reasoning: string | null;
  claims: JudgeClaim[];
  annotations: Record<number, ClaimAnnotation>;
  created_at: string;
}

export interface JudgeEvaluationsResponse {
  result_id: number;
  evaluations: JudgeEvaluation[];
}

export interface JudgeAnnotationSampleItem {
  result_id: number;
  test_question_id: number;
  question: string;
  reference_answer: string;
  response: string | null;
  evaluations: JudgeEvaluation[];
}

export interface JudgeAnnotationSampleResult {
  experiment_id: number;
  total_results: number;
  sample_size: number;
  annotated_count: number;
  sample: JudgeAnnotationSampleItem[];
}

export interface JudgeEvaluatorStats {
  evaluator_index: number;
  reliability: number | null;
  accurate_claims: number;
  inaccurate_claims: number;
  unsure_claims: number;
  total_claims_annotated: number;
  verdict_counts: Record<string, number>;
  excluded: boolean;
}

export interface JudgeReliabilityResult {
  experiment_id: number;
  evaluators: JudgeEvaluatorStats[];
  excluded_indices: number[];
  overall_reliability: number | null;
  threshold: number;
  annotation_progress: { annotated_evaluators: number; total_evaluators: number };
}

export interface JudgeSummaryResult {
  result_id: number;
  question: string;
  response: string | null;
  reference_answer: string;
  evaluator_verdicts: Record<number, string>;
  adjusted_score: number;
}

export interface JudgeSummaryResponse {
  experiment_id: number;
  excluded_indices: number[];
  results: JudgeSummaryResult[];
}

// ---------------------------------------------------------------------------
// Knowledge graph
// ---------------------------------------------------------------------------

export interface KnowledgeGraphInfo {
  exists: boolean;
  id?: number;
  project_id?: number;
  num_nodes?: number;
  num_chunks?: number;
  is_complete?: boolean;
  completed_steps?: number;
  total_steps?: number;
  heartbeat_stale?: boolean;
  chunks_stale?: boolean;
  chunk_config_id?: number;
  kg_source?: string;
  last_heartbeat?: string;
  created_at?: string;
}

export interface KGBuildProgress {
  active: boolean;
  stage?: string;
  status?: string;
  stale?: boolean;
  num_nodes?: number;
  num_chunks?: number;
  batch_current?: number;
  batch_total?: number;
  nodes_processed?: number;
  nodes_total?: number;
  is_complete?: boolean;
  completed_steps?: number;
  total_steps?: number;
}

export interface KGBuildProgressInfo {
  stage?: string;
  completed_steps: number;
  total_steps: number;
  batch_current?: number;
  batch_total?: number;
}

export interface KGListItem {
  id: number | null;
  project_id: number;
  project_name: string;
  kg_source: string;
  num_nodes: number;
  num_chunks: number;
  is_complete: boolean;
  completed_steps: number;
  total_steps: number;
  chunk_config_id: number | null;
  chunks_stale: boolean;
  created_at: string | null;
  building?: boolean;
  build_progress?: KGBuildProgressInfo;
}

export interface KGGraphNode {
  id: string;
  type: string;
  label: string;
  keyphrases: string[];
}

export interface KGGraphEdge {
  source: string;
  target: string;
  type: string;
  score: number;
}

export interface KGGraphData {
  nodes: KGGraphNode[];
  edges: KGGraphEdge[];
  is_complete: boolean;
}

export interface KGStreamCallbacks {
  onMeta: (meta: { total_nodes: number; total_edges: number; is_complete: boolean }) => void;
  onNodes: (nodes: KGGraphNode[]) => void;
  onEdges: (edges: KGGraphEdge[]) => void;
  onDone: () => void;
  onError: (error: string) => void;
}

// ---------------------------------------------------------------------------
// Workers
// ---------------------------------------------------------------------------

export interface WorkerTask {
  project_id: number;
  experiment_id?: number;
  type: 'kg_build' | 'persona_generation' | 'experiment' | 'testgen';
  kg_source?: string;
  started_at?: number;
  num_personas?: number;
  stale?: boolean;
  stage?: string;
  batch_current?: number;
  batch_total?: number;
  completed_steps?: number;
  total_steps?: number;
  phase?: string;
  current?: number;
  total?: number;
  test_set_id?: number;
  questions_generated?: number;
}

export interface WorkerInfo {
  url: string;
  reachable: boolean;
  status?: string;
  rss_mb?: number | null;
  tasks?: WorkerTask[];
  active_kg_builds?: number;
  active_persona_builds?: number;
  active_experiments?: number;
  active_testgens?: number;
  max_concurrent_kg?: number;
  max_concurrent_personas?: number;
  max_concurrent_experiments?: number;
  max_concurrent_testgens?: number;
  error?: string;
}

export interface WorkersStatusResponse {
  workers: WorkerInfo[];
  total_configured: number;
}

// ---------------------------------------------------------------------------
// Skill Arena — skills, trials, matrix, results, traces
// ---------------------------------------------------------------------------

export type SkillDirectiveKind = 'behavior' | 'format' | 'prohibition' | 'tone';

export interface SkillDirective {
  id: string;
  text: string;
  kind: SkillDirectiveKind;
  machine_checkable: boolean;
}

export interface Skill {
  id: number;
  project_id: number;
  name: string;
  version: number;
  summary: string;
  directive_count: number;
  directives: SkillDirective[];
  created_at: string;
  /** Present on POST/GET-by-id responses; absent from list responses. */
  content?: string;
}

export type SkillTrialModelSpec =
  | { kind: 'llm'; model: string }
  | { kind: 'bot'; bot_config_id: number; label?: string };

export type SkillTrialStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface SkillTrial {
  id: number;
  project_id: number;
  skill_id: number;
  name: string;
  test_set_id: number;
  models: SkillTrialModelSpec[];
  include_baseline: boolean;
  status: SkillTrialStatus;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export type SkillTrialVariant = 'skill' | 'baseline';

export interface SkillTrialCell {
  model: string;
  variant: SkillTrialVariant;
  adherence: number | null;
  format_compliance: number | null;
  avg_latency_ms: number | null;
  tokens_in: number;
  tokens_out: number;
  errors: number;
  count: number;
}

export interface SkillTrialMatrix {
  cells: SkillTrialCell[];
  /** Per-model skill-minus-baseline adherence delta. */
  lift: Record<string, number>;
}

export interface SkillTrialDetail extends SkillTrial {
  matrix: SkillTrialMatrix;
  skill?: Skill | null;
}

export interface SkillTrialCreatePayload {
  name: string;
  skill_id: number;
  test_set_id: number;
  models: SkillTrialModelSpec[];
  include_baseline: boolean;
}

export interface SkillTrialCreateResponse {
  trial_id: number;
  status: string;
  total_cells: number;
}

export interface SkillTrialProgress {
  phase: string;
  current?: number;
  total?: number;
  error?: string | null;
}

export type DirectiveVerdict = 'pass' | 'fail' | 'not_applicable';

export interface DirectiveResult {
  id: string;
  verdict: DirectiveVerdict;
  reasoning: string;
  deterministic: boolean;
}

export interface TraceSpan {
  name: string;
  offset_ms: number;
  duration_ms: number;
  status: 'ok' | 'error';
  error?: string;
}

export interface SkillTrialResult {
  id: number;
  model: string;
  variant: SkillTrialVariant;
  question_id: number;
  question: string;
  response: string | null;
  scores: {
    skill_adherence?: number | null;
    format_compliance?: number | null;
  };
  directive_results: DirectiveResult[];
  trace: TraceSpan[];
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  error: string | null;
}

export interface ApplyModelResponse {
  detail: string;
  preferred_model: string;
}
