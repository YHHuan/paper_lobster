"""Feed-based, config-driven explorers (RSS / Google News / Reddit / HN).

Distinct from `lobster/explorer/sources/` which holds question-driven adapters
used by Forager. Feed explorers are tier-rotated by Coordinator and dump
items straight into `discoveries` (no per-question routing).
"""
