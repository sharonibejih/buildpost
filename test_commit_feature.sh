#!/bin/bash

echo "=== BuildPost Commit Feature Test Script ==="
echo ""

# Test 1: Help
echo "Test 1: Showing help..."
python -m buildpost.cli commit --help
echo ""
read -p "Press Enter to continue..."

# Test 2: Check current git status
echo "Test 2: Checking git status..."
git status
echo ""
read -p "Press Enter to continue..."

# Test 3: Preview mode with test change
echo "Test 3: Creating test change and previewing commit message..."
echo "# Test at $(date)" >> TEST_FILE.md
git add TEST_FILE.md
echo ""
echo "Running: buildpost commit --no-commit"
python -m buildpost.cli commit --no-commit --output-tokens 1000
echo ""
read -p "Press Enter to continue..."

# Test 4: Different styles
# Run the commit command with a detailed style, without committing.
# --max-tokens: Sets the maximum tokens for the input diff. If not set, it's calculated automatically.
# --output-tokens: Reserves a specific number of tokens for the AI's output.
echo "Test 4: Testing commit_detailed style..."
python -m buildpost.cli commit --no-commit --style commit_detailed --max-tokens 4000 --output-tokens 1000
echo ""
read -p "Press Enter to continue..."

echo "Test 5: Testing commit_simple style..."
python -m buildpost.cli commit --no-commit --style commit_simple --output-tokens 1000
echo ""
read -p "Press Enter to continue..."

# Cleanup
echo "Cleaning up test changes..."
git reset HEAD TEST_FILE.md 2>/dev/null
rm -f TEST_FILE.md
git checkout TEST_FILE.md 2>/dev/null
echo ""

echo "=== Tests Complete ==="
echo ""
echo "Summary:"
echo "- If you saw help text, commit messages generated, and no errors: ✅ Feature is working!"
echo "- If you got API key errors: Configure with 'buildpost config set-key YOUR_KEY'"
echo "- For full testing guide, see: TESTING_COMMIT_FEATURE.md"
