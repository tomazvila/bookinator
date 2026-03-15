#!/bin/bash
OUTPUT="/private/tmp/claude-502/-Users-home-Programming-bookstuff/tasks/b2c113b.output"

while true; do
    if [ -f "$OUTPUT" ]; then
        LINES=$(wc -l < "$OUTPUT")
        OK=$(grep -c "^  OK:" "$OUTPUT" 2>/dev/null || echo 0)
        FAIL=$(grep -c "^  FAIL:" "$OUTPUT" 2>/dev/null || echo 0)
        SKIP=$(grep -c "^  SKIP" "$OUTPUT" 2>/dev/null || echo 0)
        LAST=$(tail -1 "$OUTPUT")
        echo "[$(date +%H:%M:%S)] OK: $OK | FAIL: $FAIL | SKIP: $SKIP | Last: $LAST"

        if grep -q "^Total:" "$OUTPUT" 2>/dev/null; then
            echo "=== UPLOAD COMPLETE ==="
            tail -5 "$OUTPUT"
            break
        fi
    else
        echo "Output file not found yet..."
    fi
    sleep 30
done
