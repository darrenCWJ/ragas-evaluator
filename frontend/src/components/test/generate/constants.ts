export interface SliderCategory {
  readonly key: string;
  readonly label: string;
  readonly description: string;
}

export const QUERY_TYPES = [
  {
    key: 'single_hop_specific',
    label: 'Single-hop Specific',
    description:
      'Direct factual questions answerable from a single chunk (e.g. "What is the default timeout?")',
  },
  {
    key: 'multi_hop_abstract',
    label: 'Multi-hop Abstract',
    description:
      'High-level questions requiring synthesis across multiple chunks (e.g. "How does the system handle errors?")',
  },
  {
    key: 'multi_hop_specific',
    label: 'Multi-hop Specific',
    description:
      'Precise questions needing details from multiple chunks (e.g. "Which config options affect both caching and logging?")',
  },
] as const;

export const QUESTION_CATEGORIES = [
  {
    key: 'typical',
    label: 'Typical',
    description: 'Common, expected queries users would ask in normal scenarios',
  },
  {
    key: 'in_knowledge_base',
    label: 'In Knowledge Base',
    description: 'Questions about content within the knowledge base',
  },
  { key: 'edge', label: 'Edge', description: 'Questions in unusual or challenging scenarios' },
  {
    key: 'out_of_knowledge_base',
    label: 'Out of Knowledge Base',
    description: 'Questions about content outside the knowledge base',
  },
] as const;

export const DEFAULT_CATEGORIES: Record<string, number> = {
  typical: 30,
  in_knowledge_base: 30,
  edge: 20,
  out_of_knowledge_base: 20,
};

export const GRAPH_RAG_CATEGORIES = [
  {
    key: 'bridge',
    label: 'Bridge',
    description: 'Questions connecting distant concepts through multi-hop reasoning (requires KG)',
  },
  {
    key: 'comparative',
    label: 'Comparative',
    description: 'Compare and contrast related entities or concepts (requires KG)',
  },
  {
    key: 'community',
    label: 'Community',
    description: 'High-level thematic questions about topic clusters (requires KG)',
  },
] as const;

export const DEFAULT_GRAPH_RAG_DIST: Record<string, number> = {
  bridge: 34,
  comparative: 33,
  community: 33,
};

export const DEFAULT_DISTRIBUTION: Record<string, number> = {
  single_hop_specific: 50,
  multi_hop_abstract: 25,
  multi_hop_specific: 25,
};
