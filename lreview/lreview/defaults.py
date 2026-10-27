"""Built-in defaults for the options that lreview-config.toml can set.

This is the one place to change a default. When you change a value
here, update the matching commented line in
lreview-config.example.toml: tests/test_defaults.py fails when the two
disagree. This module imports nothing, so any module can use it.
"""

# Parallel reviews, and per-review limits in seconds.
DEFAULT_JOBS = 5
DEFAULT_BENCH_JOBS = 4
DEFAULT_TIMEOUT = 7200

# Seconds a review may write nothing to its log before it is taken to
# have stalled.  The longest quiet stretch in 196 codex and 32 claude
# reviews was under four minutes.
DEFAULT_STALL_TIMEOUT = 600
DEFAULT_STALL_RETRY = True

DEFAULT_MODE = "full"
DEFAULT_AGENT = "claude"
DEFAULT_LEAN = True
DEFAULT_PRELOAD = True

# Placeholder <model> is replaced with the model that ran the review.
DEFAULT_PREFIX = "[AI review - <model>]"

# Codex reviews default to gpt-6.1-sol: astra's capability at several
# times less of the plan. Override with --model / $LREVIEW_MODEL.
CODEX_DEFAULT_MODEL = "gpt-6.1-sol"

# Sonnet 5.5 found as many known bugs as Opus 5.5 on lreview bench at
# under half the cost and time (2026-10-09). --model opus for the rest.
CLAUDE_DEFAULT_MODEL = "sonnet"

# Directory names used when no path option or variable says otherwise.
DEFAULT_RESULTS_DIRNAME = "lreview-results"
DEFAULT_WORKTREES_DIRNAME = "worktrees"
DB_DIRNAME = "lreview-db"
