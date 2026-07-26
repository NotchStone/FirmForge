"""Knowledge layer -- RAG knowledge base (规划 §3.2).

Three sub-libraries:
  reference/   Document/register reference library (JSON exact lookup)
  api/         API contract library (vector search primarily)
  community/   Community resource library (JSONL+Markdown)
  vectors/     ChromaDB vector index
"""

from firmforge.knowledge.knowledge_base import KnowledgeBase

__all__ = ["KnowledgeBase"]
