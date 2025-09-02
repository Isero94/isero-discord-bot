"""Backward-compatibility package for utility helpers.

The project reorganised utility modules under :mod:`cogs.utils`, but
some deployments still import modules using the old top-level
``utils`` package.  Importing :mod:`utils` now simply re-exports the
new locations so existing code keeps working.
"""

# re-export common helper modules
from cogs.utils.ai import *  # noqa: F401,F403
from cogs.utils.logsetup import *  # noqa: F401,F403
from cogs.utils.text import *  # noqa: F401,F403
from cogs.utils.throttling import *  # noqa: F401,F403
from cogs.utils.wake import *  # noqa: F401,F403
