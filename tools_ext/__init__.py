"""tools_ext package — focused sub-modules extracted from tools.py.

The original tools.py remains the canonical import path. These modules
provide focused groupings for new code:

    tools_ext.config  — soul/envoy/process self-modification
    tools_ext.meta    — time, tokens, memory, observer
"""

from tools_ext.config import ALL_CONFIG_TOOLS
from tools_ext.meta import ALL_META_TOOLS
