"""_debug.py

Debug switch shared by the modules that talk to the projector.
"""

import os

# Print out messages that are sent and received for debugging.
PRINT_DEBUG_COMMS = bool(os.environ.get("AIOPJLINK_PRINT_DEBUG_COMMS", False))
