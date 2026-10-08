"""cadview was renamed openworkshop (0.3.0). This package keeps the old
imports working: `from cadview import show`, `from cadview.pcb import Board`,
`python -m cadview.server` ... all resolve to openworkshop."""
from openworkshop import *                      # noqa: F401,F403
from openworkshop import Timeline, __version__  # noqa: F401
