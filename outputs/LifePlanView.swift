import SwiftUI

// MARK: - Life Plan View
// Wave 14E (2026-05-25): vision + north-star + goals + plans + wisdom
// read-only dashboard. Editing comes in a follow-up wave; this surface
// gets the data visible immediately.

struct LifePlanView: View {
    @ObservedObject var client: NCLBrainClient

    @State private var dashboard: LifeDashboard? = nil
    @State private var goals: [LifeGoal] = []
    @State private var plans: [LifePlan] = []
    @State private var loading: Bool = false
    @State private var error: String? = nil

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FSSpacing.lg) {
                if let dash = dashboard {
                    if let v = dash.vision {
                        visionCard(v)
                    } else {
                        emptyCard(title: "VISION", message: "No vision set yet. Set one via POST /life/vision.")
                    }
                    if let n = dash.northStar {
                        northStarCard(n)
                    }
                    rollupCard(dash)
                    if let w = dash.wisdomToday {
                        wisdomCard(w)
                    }
                }
                if !goals.isEmpty {
                    goalsCard
                }
                if !plans.isEmpty {
                    plansCard
                }
                if let e = error {
                    Text(e).font(FSFont.body(13)).foregroundColor(FSColor.red)
                }
                Spacer(minLength: FSSpacing.tabBarHeight)
            }
            .padding(.horizontal, FSSpacing.md)
            .padding(.top, FSSpacing.md)
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func visionCard(_ v: Vision) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            header("VISION — \(v.horizonYears)yr")
            Text(v.title).font(FSFont.body(18)).foregroundColor(FSColor.textPrimary).bold()
            if !v.narrative.isEmpty {
                Text(v.narrative).font(FSFont.body(14)).foregroundColor(FSColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !v.pillars.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(v.pillars, id: \.self) { p in
                            Text(p.uppercased())
                                .font(.system(size: 10, weight: .bold, design: .monospaced))
                                .padding(.horizontal, 8).padding(.vertical, 4)
                                .background(FSColor.orange.opacity(0.2))
                                .foregroundColor(FSColor.orange)
                                .cornerRadius(4)
                        }
                    }
                }
            }
        }.cardStyle()
    }

    private func northStarCard(_ n: NorthStar) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            header("NORTH STAR \(n.year)")
            Text(n.title).font(FSFont.body(16)).foregroundColor(FSColor.textPrimary).bold()
            if !n.measurable.isEmpty {
                Text("MEASURABLE: \(n.measurable)").font(.system(size: 12, design: .monospaced)).foregroundColor(FSColor.cyan)
            }
            if !n.why.isEmpty {
                Text(n.why).font(FSFont.body(13)).foregroundColor(FSColor.textSecondary)
            }
        }.cardStyle()
    }

    private func rollupCard(_ d: LifeDashboard) -> some View {
        HStack(spacing: 12) {
            statTile("\(d.activeGoalsCount)", "GOALS")
            statTile("\(d.activeJourneysCount)", "JOURNEYS")
            statTile("\(d.planningPlansCount)", "PLANS")
            statTile("\(d.activePlansCount)", "ACTIVE")
        }.cardStyle()
    }

    private func wisdomCard(_ w: DailyWisdom) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            header("TODAY'S WISDOM — \(w.category.uppercased())")
            Text("\u{201C}\(w.text)\u{201D}").font(FSFont.body(14)).foregroundColor(FSColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Text("— \(w.source.isEmpty ? "anon" : w.source)").font(FSFont.body(11)).foregroundColor(FSColor.textSecondary)
        }.cardStyle()
    }

    private var goalsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            header("ACTIVE GOALS (\(goals.count))")
            ForEach(goals) { g in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(g.scope.uppercased())
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(FSColor.cyan.opacity(0.2)).foregroundColor(FSColor.cyan).cornerRadius(4)
                        Spacer()
                        Text("conf \(g.confidence)/10").font(.system(size: 10, design: .monospaced)).foregroundColor(FSColor.textSecondary)
                    }
                    Text(g.objective).font(FSFont.body(14)).foregroundColor(FSColor.textPrimary)
                    ForEach(g.keyResults) { kr in
                        HStack {
                            Text("• \(kr.description)").font(FSFont.body(12)).foregroundColor(FSColor.textSecondary)
                            Spacer()
                            Text("\(Int(kr.current))/\(Int(kr.target)) \(kr.unit)")
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundColor(FSColor.green)
                        }
                    }
                }
                .padding(.vertical, 4)
            }
        }.cardStyle()
    }

    private var plansCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            header("PLANS (\(plans.count))")
            ForEach(plans) { p in
                HStack {
                    Text(p.kind.uppercased())
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(FSColor.orange.opacity(0.2)).foregroundColor(FSColor.orange).cornerRadius(4)
                    Text(p.title).font(FSFont.body(14)).foregroundColor(FSColor.textPrimary)
                    Spacer()
                    if !p.targetDate.isEmpty {
                        Text(p.targetDate).font(.system(size: 10, design: .monospaced)).foregroundColor(FSColor.cyan)
                    }
                }
            }
        }.cardStyle()
    }

    private func emptyCard(title: String, message: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            header(title)
            Text(message).font(FSFont.body(13)).foregroundColor(FSColor.textSecondary)
        }.cardStyle()
    }

    private func statTile(_ value: String, _ label: String) -> some View {
        VStack(spacing: 2) {
            Text(value).font(.system(size: 22, weight: .bold, design: .monospaced)).foregroundColor(FSColor.orange)
            Text(label).font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundColor(FSColor.textSecondary).kerning(1.0)
        }.frame(maxWidth: .infinity)
    }

    private func header(_ s: String) -> some View {
        Text(s).font(.system(size: 11, weight: .bold, design: .monospaced)).foregroundColor(FSColor.cyan).kerning(1.2)
    }

    private func load() async {
        loading = true; defer { loading = false }
        error = nil
        do {
            async let dT = try? await client.fetchLifeDashboard()
            async let gT = try? await client.fetchGoals(status: "active")
            async let pT = try? await client.fetchPlans(kind: nil)
            dashboard = await dT ?? nil
            goals = await gT ?? []
            plans = await pT ?? []
        }
    }
}

// MARK: - cardStyle helper

private extension View {
    func cardStyle() -> some View {
        self.padding(FSSpacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(FSColor.cardBg)
            .cornerRadius(8)
    }
}
