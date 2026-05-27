#!/bin/bash
set -euo pipefail
FS=/Users/natrix/Projects/FirstStrike
F=$FS/Sources/Views/JournalView.swift

# Python patch: simplify section enum to 5 tabs with explicit purpose,
# remove Councils from picker (it stays in code for compat but is hidden).
python3 <<'PYEOF'
p = '/Users/natrix/Projects/FirstStrike/Sources/Views/JournalView.swift'
src = open(p).read()

# Update CaseIterable: keep all cases internally (for back-compat with `quizSectionRouter`-style switches),
# but override `allCases` so the picker only shows the curated 5.
# Simplest path: add a static `userVisible` array and have the picker iterate that
# instead of `allCases`.

# 1) Add userVisible static after the case list. Find the enum closing brace.
if 'static let userVisible' not in src:
    src = src.replace(
        'case councils = "Councils"\n    }',
        '''case councils = "Councils"

        /// Wave 14E: curated sub-tab list shown in the picker. Older cases
        /// (Today, Reflect, Analytics, Councils) still compile so reflection
        /// + analytics features keep working under the hood, but they are
        /// folded into INSIGHTS in the visible UI per NATRIX feedback that
        /// the 9-tab picker was congested + unclear.
        static var userVisible: [JournalSection] {
            [.quiz, .lifePlan, .write, .search, .tips, .insights]
        }
    }'''
    )

# 2) Add `insights = "Insights"` case if not present
if 'case insights = "Insights"' not in src:
    src = src.replace(
        'case councils = "Councils"\n',
        'case councils = "Councils"\n        case insights = "Insights"  // Wave 14E — merged Today+Reflect+Analytics\n'
    )

# 3) Add a body case for .insights routing to a new view
if 'case .insights:' not in src:
    src = src.replace(
        'case .lifePlan:\n                            LifePlanView().environmentObject(brainClient)\n                        case .today:',
        'case .lifePlan:\n                            LifePlanView().environmentObject(brainClient)\n                        case .insights:\n                            // Wave 14E: tabs-in-one view\n                            insightsSection\n                        case .today:'
    )
    # Mirror in loadSectionData switch
    src = src.replace(
        'case .quiz, .lifePlan:\n            break  // Wave 14E — self-loading views, no preload needed\n        ',
        'case .quiz, .lifePlan, .insights:\n            break  // Wave 14E — self-loading views, no preload needed\n        '
    )

# 4) Add an insightsSection computed property. It just re-uses the existing
# todaySection + reflectSection + analyticsSection rendered in one scroll.
if 'private var insightsSection' not in src:
    # Insert before the final closing brace of the struct
    helper = '''
    /// Wave 14E — INSIGHTS = today + reflect + analytics, scrollable.
    /// Replaces three separate sub-tabs that confused NATRIX about purpose.
    @ViewBuilder
    private var insightsSection: some View {
        VStack(alignment: .leading, spacing: FSSpacing.lg) {
            sectionLabel("TODAY'S ENTRIES")
            todaySection
            Divider().padding(.vertical, 8)
            sectionLabel("REFLECTION")
            reflectSection
            Divider().padding(.vertical, 8)
            sectionLabel("ANALYTICS")
            analyticsSection
        }
    }

    private func sectionLabel(_ s: String) -> some View {
        Text(s)
            .font(.system(size: 11, weight: .bold, design: .monospaced))
            .foregroundColor(FSColor.cyan)
            .kerning(1.2)
            .padding(.bottom, 4)
    }
'''
    # Insert right before the LAST `}` of the JournalView struct.
    # Find the marker comment that precedes CouncilReportWrapper.
    marker = '// MARK: - Council Report Wrapper'
    if marker in src:
        idx = src.index(marker)
        # Walk back to the previous `}` (the JournalView struct close)
        # Insert helper before that `}`.
        # Simpler: insert helper right before the marker line minus the closing brace.
        src = src.replace(
            'private struct CouncilReportWrapper: Identifiable {',
            helper + '\n// MARK: - Council Report Wrapper (Identifiable for .sheet)\nprivate struct CouncilReportWrapper: Identifiable {'
        ).replace(
            '// MARK: - Council Report Wrapper (Identifiable for .sheet)\n// MARK: - Council Report Wrapper (Identifiable for .sheet)\nprivate struct CouncilReportWrapper',
            '// MARK: - Council Report Wrapper (Identifiable for .sheet)\nprivate struct CouncilReportWrapper'
        )
    else:
        # Fallback: append before final }
        src = src.rstrip()
        if src.endswith('}'):
            src = src[:-1] + helper + '\n}\n'

open(p, 'w').write(src)
print('patched JournalView')
PYEOF

echo
echo "=== picker source needs to use userVisible ==="
grep -n 'sectionPicker\|FSSectionPicker\|JournalSection.allCases\|JournalSection.userVisible' /Users/natrix/Projects/FirstStrike/Sources/Views/JournalView.swift | head -10
