"""
Schema-lint rule pack v1.

Importing this package is the side-effect that populates `lint_engine.registry`.
Each submodule registers its rules at import time; we re-export them from this
file so callers (notably `main.py`) only need a single import to load the v1
rule set.

Adding a rule:

  1. Create or extend a submodule (descriptions / naming / structure …).
  2. Define `_check_xyz` and call `registry.register(LintRule(...))` at module
     top level.
  3. Add the submodule to the imports below if it's new.

Rules are intentionally side-effecting on import: the engine has no
auto-discovery to keep the runtime predictable. The `_ = module` references
below silence linters about unused imports — the import itself is the load.
"""

from . import descriptions as descriptions  # noqa: F401  (registration side-effect)
from . import naming as naming  # noqa: F401  (registration side-effect)
from . import structure as structure  # noqa: F401  (registration side-effect)


__all__ = ["descriptions", "naming", "structure"]
