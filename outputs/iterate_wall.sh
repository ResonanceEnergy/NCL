#!/bin/bash
# Iteratively wall every file that fails, until build is green.
cd /Users/natrix/Projects/FirstStrike
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    xcodebuild -project FirstStrike.xcodeproj -scheme NCLDesktop -destination 'platform=macOS' build > /tmp/b.log 2>&1
    if grep -q '** BUILD SUCCEEDED **' /tmp/b.log; then
        echo "GREEN on attempt $attempt"
        exit 0
    fi
    # extract distinct source files with errors
    files=$(grep -oE '/Users/natrix/Projects/FirstStrike/Sources/Views/[A-Za-z]+\.swift' /tmp/b.log | sort -u)
    if [[ -z "$files" ]]; then
        echo "no files matched but build failed:"
        grep -E 'error:' /tmp/b.log | head -10
        exit 1
    fi
    echo "[$attempt] walling files:"
    for f in $files; do
        python3 - <<PYEOF
import re
p='$f'
s=open(p).read()
orig=s
s=s.replace('placement: .navigationBarLeading','placement: .cancellationAction')
s=s.replace('placement: .navigationBarTrailing','placement: .confirmationAction')
s=s.replace('placement: .topBarLeading','placement: .cancellationAction')
s=s.replace('placement: .topBarTrailing','placement: .confirmationAction')
for pat in [
    r'^(\s*)\.navigationBarTitleDisplayMode\([^)]+\)\s*\$',
    r'^(\s*)\.autocapitalization\([^)]+\)\s*\$',
    r'^(\s*)\.textInputAutocapitalization\([^)]+\)\s*\$',
    r'^(\s*)\.keyboardType\([^)]+\)\s*\$',
    r'^(\s*)\.statusBarHidden\([^)]*\)\s*\$',
]:
    s=re.sub(pat, lambda m: f"{m.group(1)}#if os(iOS)\n{m.group(0)}\n{m.group(1)}#endif", s, flags=re.MULTILINE)
if s!=orig:
    open(p,'w').write(s)
    print('  patched', p.split('/')[-1])
PYEOF
    done
done
echo "still failing after 10 attempts"
grep -E 'error:' /tmp/b.log | head -10
exit 1
