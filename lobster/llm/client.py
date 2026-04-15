"""Backward-compat shim — re-exports the v3 router as `LLMClient`.

New code should use `from llm.router import LLMRouter` directly.
"""

from .router import LLMRouter as LLMClient  # noqa: F401
from .router import LLMRouter  # noqa: F401
