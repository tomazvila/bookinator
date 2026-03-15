#!/bin/bash
# Monitor the scan progress
OUTPUT="/private/tmp/claude-502/-Users-home-Programming-bookstuff/tasks/bd8d7d5.output"

while true; do
    if [ -f "$OUTPUT" ]; then
        LINES=$(wc -l < "$OUTPUT")
        LAST=$(tail -1 "$OUTPUT")
        echo "[$(date +%H:%M:%S)] Lines: $LINES | Last: $LAST"

        # Check if scan is done (manifest saved line appears)
        if grep -q "Manifest saved" "$OUTPUT" 2>/dev/null; then
            echo "=== SCAN COMPLETE ==="
            tail -5 "$OUTPUT"
            break
        fi
    else
        echo "Output file not found yet..."
    fi
    sleep 30
done
