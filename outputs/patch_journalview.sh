#!/bin/bash
set -euo pipefail
F=/Users/natrix/Projects/FirstStrike/Sources/Views/JournalView.swift
BAK=$F.bak.14e

# Backup
cp "$F" "$BAK"

# 1) Extend the JournalSection enum with the two new cases at the top.
# The enum block is right after `enum JournalSection: String, CaseIterable {`
python3 <<'PYEOF'
import re
p = '/Users/natrix/Projects/FirstStrike/Sources/Views/JournalView.swift'
src = open(p).read()

# Add new enum cases at the top so they appear first in the picker
if 'case quiz = "Quiz"' not in src:
    src = src.replace(
        'enum JournalSection: String, CaseIterable {\n        case write = "Write"',
        'enum JournalSection: String, CaseIterable {\n'
        '        case quiz = "Quiz"        // Wave 14E — morning quiz keystone\n'
        '        case lifePlan = "Life"    // Wave 14E — vision / goals / plans / wisdom\n'
        '        case write = "Write"'
    )

# Add the two new switch cases at the TOP of both switches so the new
# views are reachable. Insert right before `case .today:`.
# There are TWO switch blocks at lines ~70 and ~1065 — both need the case.
quiz_block = ('case .quiz:\n'
              '                            MorningQuizView(client: client)\n'
              '                        case .lifePlan:\n'
              '                            LifePlanView(client: client)\n'
              '                        ')
src = src.replace(
    'switch selectedSection {\n                        case .today:',
    'switch selectedSection {\n                        ' + quiz_block + 'case .today:',
    1,
)

# The 2nd switch is at column 8 (different indent)
quiz_block_2 = ('case .quiz:\n'
                '            quizSectionRouter\n'
                '        case .lifePlan:\n'
                '            lifePlanSectionRouter\n'
                '        ')
# Match the second `switch selectedSection {` (loadSectionData)
parts = src.split('switch selectedSection {', 2)
if len(parts) == 3:
    # parts[2] starts with the second switch body
    parts[2] = parts[2].replace(
        'case .today:',
        quiz_block_2 + 'case .today:',
        1,
    )
    src = 'switch selectedSection {'.join(parts)

# Add tiny helpers (router stubs) just before the closing brace of the body func
# (no-op load functions for the new sections — they self-load on .task)
helpers = '''
    private var quizSectionRouter: Void {
        // MorningQuizView self-loads via .task; nothing to do here.
        ()
    }

    private var lifePlanSectionRouter: Void {
        // LifePlanView self-loads via .task; nothing to do here.
        ()
    }
'''
# Insert helpers right before the final `}` of the struct
if 'private var quizSectionRouter' not in src:
    # Find the last closing brace and insert before it
    src = src.rstrip()
    if src.endswith('}'):
        src = src[:-1] + helpers + '\n}\n'

open(p, 'w').write(src)
print('patched')
PYEOF

echo
echo "=== verify the new cases are present ==="
grep -n 'case quiz\|case lifePlan\|case .quiz\|case .lifePlan' /Users/natrix/Projects/FirstStrike/Sources/Views/JournalView.swift | head -10

echo
echo "=== regenerate xcodeproj ==="
cd /Users/natrix/Projects/FirstStrike
/opt/homebrew/bin/xcodegen generate --spec project.yml 2>&1 | tail -3

echo
echo "=== confirm new files are in the xcodeproj ==="
grep -E 'MorningQuiz|LifePlan|Journal14E' FirstStrike.xcodeproj/project.pbxproj | head -8
