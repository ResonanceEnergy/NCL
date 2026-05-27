import SwiftUI

// MARK: - Wave 14I item 10 — Capital Rotation 4-Quadrant Chart (RRG)
//
// Renders the Relative Rotation Graph from /intelligence/rotation:
//   • 4-quadrant grid: Leading (top-right green) / Improving (top-left blue) /
//     Weakening (bottom-right orange) / Lagging (bottom-left red)
//   • each of 11 SPDR sector ETFs plotted at (ratio_pct_chg_20d, rs_momentum_5d)
//   • bubble size scales with |relative_strength|, color matches quadrant
//   • top status bar: cycle phase, breadth %, leading sectors
//   • bottom: 5 style ratio rows (IWM/SPY, IWD/IWF, XLU/SPY, RSP/SPY, ARKK/SPY)

struct RotationRRGView: View {
    @EnvironmentObject var brainClient: NCLBrainClient

    @State private var envelope: RotationEnvelope? = nil
    @State private var loading = false
    @State private var lastError: String? = nil

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                if let env = envelope {
                    if let rot = env.rotation {
                        chartCard(rot)
                        quadrantBreakdown(rot)
                    } else {
                        Text("Rotation snapshot unavailable")
                            .foregroundColor(.secondary)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.vertical, 16)
                    }
                    if let style = env.styleRatios {
                        styleRatiosCard(style)
                    }
                    if let cycle = env.cyclePhase {
                        cycleCard(cycle)
                    }
                } else if loading {
                    ProgressView("Loading rotation snapshot…")
                        .frame(maxWidth: .infinity, minHeight: 200)
                } else if let err = lastError {
                    errorCard(err)
                } else {
                    Color.clear.frame(height: 100)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .background(FSColor.surface)
        .task { await refresh() }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("CAPITAL ROTATION")
                    .font(.system(size: 11, weight: .bold).monospaced())
                    .foregroundColor(FSColor.cyan)
                Text("Relative strength + momentum vs SPY")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
            Spacer()
            Button {
                Task { await refresh() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(FSColor.cyan)
            }
            .disabled(loading)
        }
    }

    // MARK: - Chart card

    private func chartCard(_ rot: RotationSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let summary = rot.leadershipSummary, !summary.isEmpty {
                Text(summary)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(FSColor.green)
            }
            if let breadth = rot.breadth {
                breadthChip(breadth)
            }
            ZStack {
                quadrantGrid()
                axisLabels()
                sectorDots(rot.sectors)
            }
            .frame(height: 320)
            .padding(.vertical, 4)
            quadrantLegend()
        }
        .padding(14)
        .background(FSColor.card)
        .cornerRadius(10)
    }

    private func breadthChip(_ b: BreadthBlock) -> some View {
        HStack(spacing: 8) {
            let pct = b.pct ?? 0
            let color: Color = pct >= 70 ? .green : pct <= 30 ? .red : .orange
            Circle().fill(color).frame(width: 8, height: 8)
            Text(String(format: "Breadth: %.0f%% (%d/%d sectors > 50d SMA)",
                        pct,
                        b.sectorsAboveSma ?? 0,
                        b.sectorsEvaluated ?? 11))
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(.secondary)
            if let regime = b.regime {
                Text(regime.replacingOccurrences(of: "_", with: " "))
                    .font(.caption2.bold())
                    .foregroundColor(color)
            }
        }
    }

    private func quadrantGrid() -> some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height
            ZStack {
                // Quadrant backgrounds
                Rectangle()
                    .fill(Color.green.opacity(0.06))
                    .frame(width: w / 2, height: h / 2)
                    .position(x: w * 0.75, y: h * 0.25)
                Rectangle()
                    .fill(Color.blue.opacity(0.06))
                    .frame(width: w / 2, height: h / 2)
                    .position(x: w * 0.25, y: h * 0.25)
                Rectangle()
                    .fill(Color.orange.opacity(0.06))
                    .frame(width: w / 2, height: h / 2)
                    .position(x: w * 0.75, y: h * 0.75)
                Rectangle()
                    .fill(Color.red.opacity(0.06))
                    .frame(width: w / 2, height: h / 2)
                    .position(x: w * 0.25, y: h * 0.75)
                // Center cross
                Path { p in
                    p.move(to: CGPoint(x: 0, y: h / 2))
                    p.addLine(to: CGPoint(x: w, y: h / 2))
                    p.move(to: CGPoint(x: w / 2, y: 0))
                    p.addLine(to: CGPoint(x: w / 2, y: h))
                }
                .stroke(Color.gray.opacity(0.35), lineWidth: 1)
                // Outer border
                Rectangle()
                    .stroke(Color.gray.opacity(0.3), lineWidth: 1)
            }
        }
    }

    private func axisLabels() -> some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height
            ZStack(alignment: .topLeading) {
                Text("IMPROVING")
                    .font(.caption2.bold())
                    .foregroundColor(.blue)
                    .position(x: w * 0.13, y: 12)
                Text("LEADING")
                    .font(.caption2.bold())
                    .foregroundColor(.green)
                    .position(x: w * 0.87, y: 12)
                Text("LAGGING")
                    .font(.caption2.bold())
                    .foregroundColor(.red)
                    .position(x: w * 0.13, y: h - 12)
                Text("WEAKENING")
                    .font(.caption2.bold())
                    .foregroundColor(.orange)
                    .position(x: w * 0.85, y: h - 12)
                // Axis hints
                Text("Momentum (5d ROC) →")
                    .font(.system(size: 8, design: .monospaced))
                    .foregroundColor(.secondary)
                    .rotationEffect(.degrees(-90))
                    .position(x: 8, y: h / 2)
                Text("← RS-Ratio (20d) →")
                    .font(.system(size: 8, design: .monospaced))
                    .foregroundColor(.secondary)
                    .position(x: w / 2, y: h - 4)
            }
        }
    }

    private func sectorDots(_ sectors: [SectorPoint]) -> some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height
            // Compute symmetric ranges so the cross stays centered.
            let xs = sectors.compactMap { $0.ratioPctChg20d }
            let ys = sectors.compactMap { $0.rsMomentum5d }
            let xMax = max(1.5, (xs.map { abs($0) }.max() ?? 1.5))
            let yMax = max(1.0, (ys.map { abs($0) }.max() ?? 1.0))
            ForEach(sectors) { s in
                if let x = s.ratioPctChg20d, let y = s.rsMomentum5d {
                    let nx = CGFloat((x / xMax + 1.0) / 2.0)  // 0..1
                    let ny = CGFloat((1.0 - (y / yMax + 1.0) / 2.0))  // flipped (up = positive)
                    let cx = nx * (w - 40) + 20
                    let cy = ny * (h - 40) + 20
                    sectorBubble(s)
                        .position(x: cx, y: cy)
                }
            }
        }
    }

    private func sectorBubble(_ s: SectorPoint) -> some View {
        let color = colorForQuadrant(s.quadrant)
        return VStack(spacing: 2) {
            Circle()
                .fill(color.opacity(0.85))
                .frame(width: 26, height: 26)
                .overlay(
                    Text(s.symbol.replacingOccurrences(of: "XL", with: ""))
                        .font(.system(size: 9, weight: .bold).monospaced())
                        .foregroundColor(.white)
                )
                .shadow(color: color.opacity(0.45), radius: 3, x: 0, y: 1)
        }
    }

    private func colorForQuadrant(_ q: String?) -> Color {
        switch q {
        case "Leading":   return .green
        case "Improving": return .blue
        case "Weakening": return .orange
        case "Lagging":   return .red
        default:          return .gray
        }
    }

    private func quadrantLegend() -> some View {
        HStack(spacing: 14) {
            legendDot(color: .green, label: "Leading")
            legendDot(color: .blue,  label: "Improving")
            legendDot(color: .orange, label: "Weakening")
            legendDot(color: .red,   label: "Lagging")
        }
        .font(.system(size: 10, design: .monospaced))
    }

    private func legendDot(color: Color, label: String) -> some View {
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(label).foregroundColor(.secondary)
        }
    }

    // MARK: - Quadrant breakdown

    private func quadrantBreakdown(_ rot: RotationSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("BY QUADRANT")
                .font(.system(size: 11, weight: .bold).monospaced())
                .foregroundColor(FSColor.cyan)
            ForEach(["Leading", "Improving", "Weakening", "Lagging"], id: \.self) { q in
                let members = rot.byQuadrant?[q] ?? []
                if !members.isEmpty {
                    HStack(spacing: 8) {
                        Circle().fill(colorForQuadrant(q)).frame(width: 8, height: 8)
                        Text(q)
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundColor(.primary)
                        Text(members.joined(separator: ", "))
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundColor(.secondary)
                        Spacer()
                    }
                }
            }
        }
        .padding(14)
        .background(FSColor.card)
        .cornerRadius(10)
    }

    // MARK: - Style ratios

    private func styleRatiosCard(_ s: StyleSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("STYLE ROTATIONS")
                .font(.system(size: 11, weight: .bold).monospaced())
                .foregroundColor(FSColor.cyan)
            ForEach(s.ratios) { r in
                styleRatioRow(r)
            }
            if let signals = s.regimeSignals, !signals.isEmpty {
                Text(signals.joined(separator: " · "))
                    .font(.caption2.monospaced())
                    .foregroundColor(.secondary)
                    .padding(.top, 4)
            }
        }
        .padding(14)
        .background(FSColor.card)
        .cornerRadius(10)
    }

    private func styleRatioRow(_ r: StyleRatio) -> some View {
        let dir = r.direction ?? "neutral"
        let dirColor: Color = {
            switch dir {
            case "rotating_in", "trending_up":   return .green
            case "rotating_out", "trending_down": return .red
            default: return .secondary
            }
        }()
        return HStack(spacing: 10) {
            Text(r.ratio)
                .font(.system(size: 12, weight: .bold).monospaced())
                .frame(width: 90, alignment: .leading)
            VStack(alignment: .leading, spacing: 0) {
                Text(r.label ?? "")
                    .font(.caption)
                    .foregroundColor(.primary)
                Text(r.interpretation ?? "")
                    .font(.system(size: 9))
                    .foregroundColor(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 0) {
                if let d5 = r.fiveDayPct {
                    Text(String(format: "%+.2f%% 5d", d5))
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(dirColor)
                }
                if let d20 = r.twentyDayPct {
                    Text(String(format: "%+.2f%% 20d", d20))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(.secondary)
                }
            }
            Circle().fill(dirColor).frame(width: 8, height: 8)
        }
    }

    // MARK: - Cycle phase

    private func cycleCard(_ c: CycleSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("BUSINESS CYCLE")
                .font(.system(size: 11, weight: .bold).monospaced())
                .foregroundColor(FSColor.cyan)
            if let cls = c.classification {
                HStack(spacing: 10) {
                    Text((cls.phase ?? "unknown").uppercased().replacingOccurrences(of: "_", with: " "))
                        .font(.system(size: 14, weight: .bold))
                        .foregroundColor(phaseColor(cls.phase))
                    if let conf = cls.confidence {
                        Text(String(format: "conf %.2f", conf))
                            .font(.caption.monospaced())
                            .foregroundColor(.secondary)
                    }
                    Spacer()
                }
                if let exp = cls.expectedLeaders, !exp.isEmpty {
                    HStack(spacing: 6) {
                        Text("Expected leaders:")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text(exp.joined(separator: ", "))
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(.primary)
                    }
                }
                if let reasons = cls.reasons, !reasons.isEmpty {
                    Text(reasons.joined(separator: " · "))
                        .font(.caption2)
                        .foregroundColor(.secondary)
                        .padding(.top, 2)
                }
            }
        }
        .padding(14)
        .background(FSColor.card)
        .cornerRadius(10)
    }

    private func phaseColor(_ phase: String?) -> Color {
        switch phase {
        case "early_expansion": return .green
        case "mid_cycle":       return .blue
        case "late_cycle":      return .orange
        case "recession":       return .red
        default:                return .secondary
        }
    }

    // MARK: - Error state

    private func errorCard(_ err: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 28))
                .foregroundColor(.orange)
            Text("Couldn't load rotation")
                .font(.headline)
            Text(err)
                .font(.caption.monospaced())
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
            Button("Retry") {
                Task { await refresh() }
            }
        }
        .frame(maxWidth: .infinity, minHeight: 200)
    }

    // MARK: - Data refresh

    @MainActor
    private func refresh() async {
        loading = true
        lastError = nil
        defer { loading = false }
        do {
            let env = try await brainClient.fetchRotation()
            // If today's snapshot is empty, kick the build.
            if env.rotation == nil && env.styleRatios == nil && env.cyclePhase == nil {
                let fired = try await brainClient.fireRotationBuild()
                self.envelope = fired
            } else {
                self.envelope = env
            }
        } catch {
            self.lastError = "\(error)"
        }
    }
}
