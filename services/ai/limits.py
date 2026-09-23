"""Hard limits on every AI request (docs/CONTROL-LAB.md §10, Phase 8).

Explicit constants rather than configuration, so a limit is visible in a
code review and can't be raised by accident. Every one is enforced in
code before or after the model call -- none relies on the model obeying
an instruction.
"""

# Generation
MAX_SCENARIOS_PER_REQUEST = 5        # candidates a single request may produce
MAX_REQUEST_CHARS = 2_000            # the engineer's free-text request
MAX_GENERATION_OUTPUT_TOKENS = 8_000  # includes the model's thinking

# Analysis
MAX_ANALYSIS_OUTPUT_TOKENS = 6_000
MAX_ANALYSIS_INPUT_CHARS = 16_000    # the whole serialized digest sent for one run
MAX_ANALYSIS_EVENTS = 40             # events kept, nearest the failure
MAX_TAG_CHANGES = 60                 # tag transitions kept, nearest the failure
ANALYSIS_WINDOW_S = 3.0              # simulated seconds either side of the failure point

# Shared
MAX_CONTEXT_CHARS = 24_000           # the system-description context for generation
