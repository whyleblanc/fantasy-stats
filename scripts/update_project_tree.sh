#!/usr/bin/env bash
set -euo pipefail

# Always run from repo root
cd "$(dirname "$0")/.."

IGNORE="node_modules|.venv|__pycache__|dist|build|.git"
MAX_DEPTH=10

############################################
# 1. Developer-facing tree snapshot
############################################
tree -I "$IGNORE" -L "$MAX_DEPTH" > PROJECT_TREE.md

############################################
# 2. GPT-friendly project tree
############################################
cat > GPT_PROJECT_TREE.md <<EOF
# Fantasy Basketball Stats – Project Tree (For GPT)

This file is for the Custom GPT. It shows the repository layout so the model
understands where backend, frontend, analytics, and engine code live.

Do not assume files exist beyond what is listed here.

\`\`\`text
$(tree -I "$IGNORE" -L "$MAX_DEPTH")
\`\`\`
EOF

############################################
# 3. GPT-friendly project context
############################################
if [[ -f PROJECT_CONTEXT.md ]]; then
  cat > GPT_PROJECT_CONTEXT.md <<EOF
# Fantasy Basketball Stats – Project Context (For GPT)

This file mirrors PROJECT_CONTEXT.md and captures the purpose, architecture,
and constraints of the Fantasy Basketball Stats platform.

Below is the exact content:

\`\`\`markdown
$(cat PROJECT_CONTEXT.md)
\`\`\`
EOF
  echo "Updated GPT_PROJECT_CONTEXT.md"
else
  echo "WARNING: PROJECT_CONTEXT.md not found; GPT_PROJECT_CONTEXT.md skipped" >&2
fi

############################################
# 4. Validate doctrine files (do NOT overwrite)
############################################

# Analytics Doctrine
if [[ -f GPT_ANALYTICS_NOTES.md ]]; then
  echo "GPT_ANALYTICS_NOTES.md found."
else
  echo "WARNING: GPT_ANALYTICS_NOTES.md not found. Add it to the repo root." >&2
fi

# API Contracts
if [[ -f GPT_API_CONTRACTS.md ]]; then
  echo "GPT_API_CONTRACTS.md found."
else
  echo "WARNING: GPT_API_CONTRACTS.md not found. Add it to the repo root." >&2
fi

############################################
# 5. Build bundle directory for GPT uploads
############################################
BUNDLE_DIR="gpt_knowledge_bundle"
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR"

# Always include tree + context if available
cp GPT_PROJECT_TREE.md "$BUNDLE_DIR"/ || true
[[ -f GPT_PROJECT_CONTEXT.md ]] && cp GPT_PROJECT_CONTEXT.md "$BUNDLE_DIR"/

# Include doctrine files if they exist
[[ -f GPT_ANALYTICS_NOTES.md ]] && cp GPT_ANALYTICS_NOTES.md "$BUNDLE_DIR"/
[[ -f GPT_API_CONTRACTS.md ]] && cp GPT_API_CONTRACTS.md "$BUNDLE_DIR"/

############################################
# 6. Add README explaining contents
############################################
cat > "$BUNDLE_DIR/README.md" <<EOF
# GPT Knowledge Bundle

This folder contains all files intended for upload into your Custom GPT.

## Included Files

### GPT_PROJECT_TREE.md
Repository structure. Helps the GPT reason about where code lives.

### GPT_PROJECT_CONTEXT.md
High-level project purpose, architecture, decisions, and constraints.

### GPT_ANALYTICS_NOTES.md
All analytical doctrine: z-scores, power metrics, dominance, luck, fraud, regression, narrative rules.

### GPT_API_CONTRACTS.md
Canonical description of endpoint inputs/outputs. Prevents hallucinated schema.

### README.md
This file.

## Usage
Upload this folder (or the ZIP file) to the Custom GPT under:
**Configure → Knowledge**.
EOF

############################################
# 7. Zip the knowledge bundle
############################################
if command -v zip >/dev/null 2>&1; then
  rm -f GPT_KNOWLEDGE_BUNDLE.zip
  zip -r GPT_KNOWLEDGE_BUNDLE.zip "$BUNDLE_DIR" >/dev/null
  echo "Created GPT_KNOWLEDGE_BUNDLE.zip"
else
  echo "WARNING: 'zip' command not found; bundle not zipped." >&2
fi

echo "All GPT knowledge files updated and packaged."