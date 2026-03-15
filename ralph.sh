#!/bin/bash

# Ralph Wiggum Loop for BookStuff Development
# Reads PRD.md and works through tasks until tests pass
# Usage: ./ralph.sh [max_iterations]

# Ensure claude and nix are in PATH
export PATH="$HOME/.local/bin:$HOME/.nix-profile/bin:/nix/var/nix/profiles/default/bin:/opt/homebrew/bin:$PATH"

# --- Helper Functions ---

# Show spinner while a process runs (for fallback mode)
show_spinner() {
    local pid=$1
    local spin='-\|/'
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r>>> Claude is working... %c (PID: %d)" "${spin:i++%4:1}" "$pid"
        sleep 0.5
    done
    printf "\r>>> Claude finished.                              \n"
}

# Run claude with real-time streaming output using --output-format stream-json
run_claude_streaming() {
    local prompt="$1"
    local output_file="$2"
    local raw_file="/tmp/ralph_raw_$$.json"

    echo ">>> Using Claude's native stream-json output"
    echo ""

    # Clear output file
    > "$output_file"

    # Use stream-json format for real-time output
    if command -v jq &> /dev/null; then
        # Use jq for reliable JSON parsing
        claude --print --output-format stream-json --verbose --dangerously-skip-permissions -p "$prompt" 2>&1 | \
        tee "$raw_file" | \
        while IFS= read -r line; do
            # Skip empty lines
            [ -z "$line" ] && continue

            # Parse with jq - extract message type and content
            msg_type=$(echo "$line" | jq -r '.type // empty' 2>/dev/null)

            case "$msg_type" in
                "assistant")
                    # Main text content
                    content=$(echo "$line" | jq -r '.message.content[]? | select(.type=="text") | .text // empty' 2>/dev/null)
                    if [ -n "$content" ]; then
                        printf "%s" "$content"
                        printf "%s" "$content" >> "$output_file"
                    fi
                    ;;
                "content_block_start")
                    # Tool use start
                    tool_name=$(echo "$line" | jq -r '.content_block.name // empty' 2>/dev/null)
                    if [ -n "$tool_name" ]; then
                        printf "\n>>> [Tool: %s]\n" "$tool_name"
                        printf "\n>>> [Tool: %s]\n" "$tool_name" >> "$output_file"
                    fi
                    ;;
                "content_block_delta")
                    # Streaming text delta
                    delta=$(echo "$line" | jq -r '.delta.text // empty' 2>/dev/null)
                    if [ -n "$delta" ]; then
                        printf "%s" "$delta"
                        printf "%s" "$delta" >> "$output_file"
                    fi
                    ;;
                "result")
                    # Final result - extract any remaining content
                    content=$(echo "$line" | jq -r '.result // empty' 2>/dev/null)
                    if [ -n "$content" ] && [ "$content" != "null" ]; then
                        printf "%s\n" "$content"
                        printf "%s\n" "$content" >> "$output_file"
                    fi
                    ;;
            esac
        done || true
    else
        # Fallback: sed-based parsing (less reliable)
        echo ">>> (Install jq for better output parsing: brew install jq)"
        claude --print --output-format stream-json --verbose --dangerously-skip-permissions -p "$prompt" 2>&1 | \
        tee "$raw_file" | \
        while IFS= read -r line; do
            if [[ "$line" == *'"text"'* ]]; then
                content=$(echo "$line" | sed -n 's/.*"text":"\([^"]*\)".*/\1/p' 2>/dev/null)
                if [ -n "$content" ]; then
                    content=$(echo "$content" | sed 's/\\n/\n/g; s/\\t/\t/g; s/\\"/"/g')
                    printf "%s" "$content"
                    printf "%s" "$content" >> "$output_file"
                fi
            fi
        done || true
    fi

    echo ""
    rm -f "$raw_file" 2>/dev/null
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/PRD.md"
MAX_ITERATIONS="${1:-50}"
ITERATION=0
OUTPUT_FILE="/tmp/ralph_output_$$.txt"
LOG_FILE="$SCRIPT_DIR/ralph_log.md"

if [ ! -f "$PRD_FILE" ]; then
    echo "Error: PRD.md not found at $PRD_FILE"
    exit 1
fi

# Check claude is available
if ! command -v claude &> /dev/null; then
    echo "Error: 'claude' command not found in PATH"
    echo "PATH: $PATH"
    echo "Try: which claude"
    exit 1
fi

echo "=== Ralph Wiggum Loop ==="
echo "PRD: $PRD_FILE"
echo "Max iterations: $MAX_ITERATIONS"
echo "Progress log: $LOG_FILE"
echo "Streaming: native (--output-format stream-json)"
echo "========================="

# Initialize or append to log
echo "" >> "$LOG_FILE"
echo "# Ralph Session $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

PROMPT="You are working on the BookStuff project — an e-book scanner, classifier, and uploader.

FIRST: Read PRD.md and ralph_log.md (if exists) to understand the project and previous progress.

THEN: Check current state:
- What files exist in src/bookstuff/ and tests/?
- Does flake.nix exist? Can you run: nix develop --command python -m pytest tests/ -v
- What tests pass/fail?

PICK a task from PRD.md that makes sense given current state. Tasks are PARALLEL - pick whichever is:
- Unblocked (dependencies ready — Task 1 scaffolding must be done first)
- Has failing or missing tests
- Makes progress toward the goal

WORKFLOW:
1. Write/update tests FIRST
2. Implement until tests pass
3. Run: nix develop --command python -m pytest tests/ -v -m 'not integration'
4. If stuck, switch to a different task

IMPORTANT:
- All Python deps must be in flake.nix (ebooklib, pymupdf, click, anthropic, etc.)
- Unit tests must use mocks — do NOT SSH to real servers or scan real directories in unit tests
- Integration tests (test_integration.py) CAN SSH to the real server — mark with @pytest.mark.integration
- The default pytest run should NOT run integration tests. Use: pytest tests/ -v -m 'not integration'
- Never delete any files on the remote server or locally
- Keep test fixtures small (tiny sample EPUBs/PDFs in test_fixtures/)
- ANTHROPIC_API_KEY env var must be available for classifier tests (mock it in unit tests)

END your response with:
## Iteration Summary
- Task worked on: [task name]
- Files changed: [list]
- Tests: [X passing, Y failing]
- Next: [what to do next iteration]

When ALL tests pass and all tasks are implemented: output RALPH_COMPLETE"

while [ $ITERATION -lt $MAX_ITERATIONS ]; do
    ITERATION=$((ITERATION + 1))
    echo ""
    echo "=========================================="
    echo ">>> ITERATION $ITERATION of $MAX_ITERATIONS"
    echo ">>> $(date)"
    echo "=========================================="
    echo ""

    # Run Claude Code with real-time streaming output
    echo ">>> Started at $(date)"
    echo ""

    run_claude_streaming "$PROMPT" "$OUTPUT_FILE"

    echo ""
    echo ">>> Finished at $(date)"

    # Check for completion signal in the output
    if grep -q "RALPH_COMPLETE" "$OUTPUT_FILE"; then
        echo ""
        echo "=== COMPLETION SIGNAL RECEIVED ==="
        echo "Verifying tests..."

        cd "$SCRIPT_DIR"
        if nix develop --command python -m pytest tests/ -v -m 'not integration' 2>&1 | tee /tmp/ralph_final_test.txt; then
            if ! grep -qE "FAILED|ERROR" /tmp/ralph_final_test.txt; then
                echo ""
                echo "=========================================="
                echo "=== SUCCESS on iteration $ITERATION ==="
                echo "=========================================="
                exit 0
            fi
        fi
        echo "Tests not fully passing, continuing..."
    fi

    # Extract and log the iteration summary
    echo "" >> "$LOG_FILE"
    echo "### Iteration $ITERATION - $(date)" >> "$LOG_FILE"
    # Capture everything after "## Iteration Summary" if present
    if grep -q "## Iteration Summary" "$OUTPUT_FILE"; then
        sed -n '/## Iteration Summary/,$p' "$OUTPUT_FILE" >> "$LOG_FILE"
    else
        echo "No summary provided" >> "$LOG_FILE"
    fi
    echo "" >> "$LOG_FILE"

    echo ""
    echo ">>> Iteration $ITERATION complete, logged to ralph_log.md"
    sleep 2
done

echo ""
echo "=========================================="
echo "=== MAX ITERATIONS REACHED ($MAX_ITERATIONS) ==="
echo "=========================================="
exit 1
