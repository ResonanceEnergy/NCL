#!/bin/bash
set -euo pipefail
FS=/Users/natrix/Projects/FirstStrike
SRC=/Users/natrix/dev/NCL/outputs

cp "$SRC/LifePlanEditors.swift" "$FS/Sources/Views/Journal/LifePlanEditors.swift"
echo "copied LifePlanEditors.swift"

# Patch LifePlanView to expose editor sheets via toolbar + + buttons.
python3 <<'PYEOF'
p = '/Users/natrix/Projects/FirstStrike/Sources/Views/Journal/LifePlanView.swift'
src = open(p).read()

# 1) Add @State for sheet routing right after existing @State lines
state_block = '''    @State private var loading: Bool = false
    @State private var error: String? = nil'''
new_state_block = state_block + '''

    // Wave 14F — editor sheets
    @State private var showVisionEditor = false
    @State private var showGoalEditor = false
    @State private var showPlanEditor = false
    @State private var showVisionBoard = false'''
if '@State private var showVisionEditor' not in src:
    src = src.replace(state_block, new_state_block, 1)

# 2) Add an Action Bar at the top of the ScrollView VStack.
# Insert it right after the opening of the main VStack.
marker = '            VStack(alignment: .leading, spacing: FSSpacing.lg) {\n                if let dash = dashboard {'
action_bar = '''            VStack(alignment: .leading, spacing: FSSpacing.lg) {
                // Wave 14F action bar
                actionBar
                if let dash = dashboard {'''
if 'actionBar' not in src:
    src = src.replace(marker, action_bar, 1)

# 3) Add sheets + actionBar helper before the cardStyle extension at the bottom
new_helpers = '''
    private var actionBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                actionBtn(\"+ VISION\", color: FSColor.cyan) { showVisionEditor = true }
                actionBtn(\"+ GOAL\", color: FSColor.green) { showGoalEditor = true }
                actionBtn(\"+ PLAN\", color: FSColor.orange) { showPlanEditor = true }
                actionBtn(\"VISION BOARD\", color: FSColor.purple) { showVisionBoard = true }
            }
        }
        .sheet(isPresented: $showVisionEditor) {
            VisionEditorSheet(existing: dashboard?.vision, onSaved: { Task { await load() } })
                .environmentObject(client)
        }
        .sheet(isPresented: $showGoalEditor) {
            GoalEditorSheet(onSaved: { Task { await load() } })
                .environmentObject(client)
        }
        .sheet(isPresented: $showPlanEditor) {
            PlanEditorSheet(onSaved: { Task { await load() } })
                .environmentObject(client)
        }
        .sheet(isPresented: $showVisionBoard) {
            VisionBoardSheet().environmentObject(client)
        }
    }

    private func actionBtn(_ label: String, color: Color, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(color.opacity(0.2)).foregroundColor(color).cornerRadius(6)
        }
    }
'''
if 'actionBtn' not in src:
    # Insert before the file-level `private extension View`
    src = src.replace('// MARK: - cardStyle helper', new_helpers + '\n// MARK: - cardStyle helper')

open(p, 'w').write(src)
print('patched LifePlanView')
PYEOF

# Patch JournalView insightsSection to add review buttons
python3 <<'PYEOF'
p = '/Users/natrix/Projects/FirstStrike/Sources/Views/JournalView.swift'
src = open(p).read()

# Add review sheets state and presentation
state_block = '@EnvironmentObject var brainClient: NCLBrainClient'
new_state_block = state_block + '''
    // Wave 14F — review wizards
    @State private var showWeeklyReview = false
    @State private var showYearlyReview = false'''
if 'showWeeklyReview' not in src:
    src = src.replace(state_block, new_state_block, 1)

# Find the insightsSection definition and inject review-button bar at the top
insights_marker = '''    private var insightsSection: some View {
        VStack(alignment: .leading, spacing: FSSpacing.lg) {
            sectionLabel(\"TODAY'S ENTRIES\")'''
new_insights = '''    private var insightsSection: some View {
        VStack(alignment: .leading, spacing: FSSpacing.lg) {
            // Wave 14F — review wizard buttons
            HStack(spacing: 8) {
                Button { showWeeklyReview = true } label: {
                    Text(\"WEEKLY REVIEW\").font(.system(size: 11, weight: .bold, design: .monospaced))
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(FSColor.cyan.opacity(0.2)).foregroundColor(FSColor.cyan).cornerRadius(6)
                }
                Button { showYearlyReview = true } label: {
                    Text(\"YEARLY REVIEW\").font(.system(size: 11, weight: .bold, design: .monospaced))
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(FSColor.purple.opacity(0.2)).foregroundColor(FSColor.purple).cornerRadius(6)
                }
                Spacer()
            }
            .sheet(isPresented: $showWeeklyReview) { WeeklyReviewSheet().environmentObject(brainClient) }
            .sheet(isPresented: $showYearlyReview) { YearlyReviewSheet().environmentObject(brainClient) }
            sectionLabel(\"TODAY'S ENTRIES\")'''
if 'showWeeklyReview = true' not in src:
    src = src.replace(insights_marker, new_insights, 1)

open(p, 'w').write(src)
print('patched JournalView')
PYEOF

echo === regen xcodeproj ===
cd "$FS" && /opt/homebrew/bin/xcodegen generate --spec project.yml 2>&1 | tail -2
echo === confirm new file registered ===
grep -c 'LifePlanEditors' "$FS/FirstStrike.xcodeproj/project.pbxproj"
echo === build ===
TS=$(date +%H%M%S)
(nohup xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike -destination 'generic/platform=iOS Simulator' -configuration Debug -derivedDataPath build/SimDerived CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build > build/sim-logs/sim-14f-${TS}.log 2>&1 &)
(nohup xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike -destination 'generic/platform=iOS' -configuration Debug -derivedDataPath build/DevDerived -allowProvisioningUpdates CODE_SIGN_STYLE=Automatic DEVELOPMENT_TEAM=N3C5G3SU3T build > build/dev-logs/dev-14f-${TS}.log 2>&1 &)
echo TS=${TS}
