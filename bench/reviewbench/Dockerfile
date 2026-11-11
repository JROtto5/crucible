# crucible wrapped for ReviewBench (https://github.com/review-bench/ReviewBench, AGENT_CONTRACT.md).
# Credential: CLAUDE_CODE_OAUTH_TOKEN (or ANTHROPIC_API_KEY), handed in at run time, never baked in.
# The Claude Code CLI binary is copied in from the build context (./claude, not committed).
# Configuration (RB_CONFIG_*): BUDGET (USD per PR, default 8), CRUCIBLE_REF (informational).
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates jq ripgrep \
    && rm -rf /var/lib/apt/lists/*
ARG CRUCIBLE_REF=main
RUN pip install --no-cache-dir "git+https://github.com/JROtto5/crucible@${CRUCIBLE_REF}"
COPY claude /usr/local/bin/claude
COPY agent.sh to_findings.py /agent/
RUN chmod 755 /usr/local/bin/claude /agent/agent.sh
ENTRYPOINT ["/agent/agent.sh"]
