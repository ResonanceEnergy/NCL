#!/bin/bash
set -euo pipefail

# Fix 1: Switch the new views from passed client to @EnvironmentObject brainClient
python3 <<'PYEOF'
for p in [
    '/Users/natrix/Projects/FirstStrike/Sources/Views/Journal/MorningQuizView.swift',
    '/Users/natrix/Projects/FirstStrike/Sources/Views/Journal/LifePlanView.swift',
]:
    src = open(p).read()
    # Replace `@ObservedObject var client: NCLBrainClient` with EnvironmentObject brainClient
    src = src.replace('@ObservedObject var client: NCLBrainClient',
                      '@EnvironmentObject var client: NCLBrainClient')
    open(p, 'w').write(src)
    print(f'patched: {p}')
PYEOF

# Fix 2: Remove the broken helper stubs that landed in CouncilReportWrapper +
# change the 2nd switch's quiz/lifePlan cases to use EmptyView (no data load needed)
python3 <<'PYEOF'
p = '/Users/natrix/Projects/FirstStrike/Sources/Views/JournalView.swift'
src = open(p).read()

# Remove the bad helper block from CouncilReportWrapper
bad_helpers = '''
    private var quizSectionRouter: Void {
        // MorningQuizView self-loads via .task; nothing to do here.
        ()
    }

    private var lifePlanSectionRouter: Void {
        // LifePlanView self-loads via .task; nothing to do here.
        ()
    }
'''
src = src.replace(bad_helpers, '')

# In the 2nd switch (loadSectionData), the new cases reference non-existent
# helpers. Replace with explicit `break` for the new cases.
src = src.replace(
    'case .quiz:\n            quizSectionRouter\n        case .lifePlan:\n            lifePlanSectionRouter\n        ',
    'case .quiz, .lifePlan:\n            break  // Wave 14E — self-loading views, no preload needed\n        ',
)

# Fix 1st switch — view constructor needs no client arg (uses @EnvironmentObject)
src = src.replace('MorningQuizView(client: client)', 'MorningQuizView()')
src = src.replace('LifePlanView(client: client)', 'LifePlanView()')

# Pre-construct the views via brainClient for inline render
src = src.replace(
    'case .quiz:\n                            MorningQuizView()\n                        case .lifePlan:\n                            LifePlanView()',
    'case .quiz:\n                            MorningQuizView().environmentObject(brainClient)\n                        case .lifePlan:\n                            LifePlanView().environmentObject(brainClient)',
)

open(p, 'w').write(src)
print('patched JournalView')
PYEOF

echo
echo "=== last 30 lines of JournalView (verify wrapper struct fixed) ==="
tail -15 /Users/natrix/Projects/FirstStrike/Sources/Views/JournalView.swift

echo
echo "=== rebuild ==="
cd /Users/natrix/Projects/FirstStrike
TS=$(date +%H%M%S)
(nohup xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'generic/platform=iOS Simulator' -configuration Debug \
  -derivedDataPath build/SimDerived \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build \
  > build/sim-logs/sim-14e-r3-${TS}.log 2>&1 &)
(nohup xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'generic/platform=iOS' -configuration Debug \
  -derivedDataPath build/DevDerived \
  -allowProvisioningUpdates CODE_SIGN_STYLE=Automatic DEVELOPMENT_TEAM=N3C5G3SU3T build \
  > build/dev-logs/dev-14e-r3-${TS}.log 2>&1 &)
echo "TS=${TS}" > /tmp/fs14e3
date
echo backgrounded
