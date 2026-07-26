#!/bin/bash
# Install git pre-commit hook
# Run once: bash scripts/install-hook.sh

HOOK=".git/hooks/pre-commit"

cat > "$HOOK" << 'EOF'
#!/bin/bash
set -e

echo "=== Pre-commit: ruff lint ==="
python -m ruff check firmforge/ --ignore E501,F841 || { echo "Lint failed"; exit 1; }

echo "=== Pre-commit: pytest ==="
python -m pytest tests/ -q || { echo "Tests failed"; exit 1; }

echo "All checks passed."
EOF

chmod +x "$HOOK"
echo "Hook installed → .git/hooks/pre-commit"
