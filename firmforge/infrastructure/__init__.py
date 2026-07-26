"""Infrastructure -- shared facilities.

Modules:
- HIL Framework: assert + serial collection
- Skills Repo: four-category YAML skeleton
- Tracing Logger: JSONL local
- platform_config.yaml: multi-platform version tracking
"""

from firmforge.infrastructure.tracing import TracingLogger
from firmforge.infrastructure.hil import HILFramework, HILTestResult, HILTestAssertion

__all__ = ["TracingLogger", "HILFramework", "HILTestResult", "HILTestAssertion"]
