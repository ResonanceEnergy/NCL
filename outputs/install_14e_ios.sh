#!/bin/bash
set -euo pipefail

FS=/Users/natrix/Projects/FirstStrike
SRC=/Users/natrix/dev/NCL/outputs

echo "=== copying iOS swift files ==="
mkdir -p "$FS/Sources/Views/Journal"

cp "$SRC/MorningQuiz.swift"                  "$FS/Sources/Models/MorningQuiz.swift"
cp "$SRC/NCLBrainClient+Journal14E.swift"    "$FS/Sources/Network/NCLBrainClient+Journal14E.swift"
cp "$SRC/MorningQuizView.swift"              "$FS/Sources/Views/Journal/MorningQuizView.swift"
cp "$SRC/LifePlanView.swift"                 "$FS/Sources/Views/Journal/LifePlanView.swift"

ls -la "$FS/Sources/Models/MorningQuiz.swift" "$FS/Sources/Network/NCLBrainClient+Journal14E.swift" "$FS/Sources/Views/Journal/MorningQuizView.swift" "$FS/Sources/Views/Journal/LifePlanView.swift"

echo
echo "=== check JournalView enum + body ==="
grep -n 'enum JournalSection' "$FS/Sources/Views/JournalView.swift"
sed -n '46,62p' "$FS/Sources/Views/JournalView.swift"
