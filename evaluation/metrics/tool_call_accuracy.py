"""Tool call accuracy — strict, order-aware tool-call scoring.

Thin re-export: the scorer lives in ``agent_trace`` alongside ``tool_call_f1``
(they share normalization/matching helpers). Computed deterministically from
the recorded agent trace by the experiment runner — no LLM cost.

(Replaces an unwired ragas ToolCallAccuracy stub — ragas' version needs
multi-turn conversation objects this app's single-turn traces don't have.)
"""

from evaluation.metrics.agent_trace import tool_call_accuracy_score

__all__ = ["tool_call_accuracy_score"]
