"""dataIpsum: gerador de dados sintéticos determinístico e extensível.

Façade pública: reexporta `dataipsum.api` (DD-00 §3.8).
"""

import importlib.metadata

from dataipsum.api import (
    RunOptions,
    RunResult,
    export_schema,
    generate,
    import_ddl,
    load_schema,
    plan,
    resume,
    validate,
)

__version__ = importlib.metadata.version("dataipsum")

__all__ = [
    "RunOptions",
    "RunResult",
    "__version__",
    "export_schema",
    "generate",
    "import_ddl",
    "load_schema",
    "plan",
    "resume",
    "validate",
]
