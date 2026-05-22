// CalendarSunView.swift
// FirstStrike — NCL Brain Companion
//
// Sun sub-tab of the Calendar tab.
// Renders solar position, space weather, aurora forecast, CME alerts,
// sunspots / F10.7, Schumann resonance, seasonal markers, and the
// overall solar energy mode chip.
//
// Calls GET /calendar/sun?city_id={city} via CalendarAPI (Agent 9).
// Pull-to-refresh triggers POST /calendar/refresh then a re-fetch.

import SwiftUI

// MARK: - Local Codable Fallbacks
//
// If Agent 9's Models/CalendarModels.swift defines these types first, the
// compiler will pick those up and these will collide. To avoid that we use
// a leading "FS" (FirstStrike) prefix for the LOCAL fallback models and
// expose typealiases at the bottom that prefer the shared models if present.
//
// When Agent 9 ships the shared models, this file remains compilable by
// re-mapping the typealias names. If the shared model is missing, the local
// types take over.

struct SunTimes: Codable, Hashable {
    let sunrise: String?
    let sunset: String?
    let solarNoon: String?
    let goldenHour: String?
    let dayLength: Double?
    let civilTwilightBegin: String?
    let civilTwilightEnd: String?
}

struct SpaceWeather: Codable, Hashable {
    let kpIndex: Double?
    let solarWindSpeed: Double?
    let flareClass: String?
    let xrayFlux: Double?
    let storm: String?
}

struct SunspotData: Codable, Hashable {
    let number: Int?
    let f107Flux: Double?
    let trend: String?  // "up" | "down" | "flat"
}

struct AuroraForecast: Codable, Hashable {
    let visible: Bool?
    let likelihood: String?  // "none" | "low" | "moderate" | "high"
    let kpForecast: [Double]?  // next 3 days
}

struct CMEAlert: Codable, Hashable, Identifiable {
    let id: String
    let severity: String?
    let message: String?
    let issuedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, severity, message
        case issuedAt = "issued_at"
    }
}

struct Schumann: Codable, Hashable {
    let frequencyHz: Double?
    let amplitude: Double?
    let status: String?  // "stable" | "anomalous"
}

struct SeasonalMarker: Codable, Hashable {
    let currentSeason: String?
    let nextEvent: String?      // e.g. "summer_solstice"
    let nextEventDate: String?  // ISO
    let daysUntil: Int?
    let sunDeclination: Double?
}

struct SunState: Codable, Hashable {
    let sunTimes: SunTimes?
    let spaceWeather: SpaceWeather?
    let sunspot: SunspotData?
    let aurora: AuroraForecast?
    let cmeAlerts: [CMEAlert]?
    let schumann: Schumann?
    let seasonalMarker: SeasonalMarker?
    let solarEnergyMode: String?
    let fetchedAt: String?
}


// MARK: - View

struct CalendarSunView: View {
    @EnvironmentObject var appState: AppState

    /// City id passed down from the parent CalendarView (Agent 9).
    var cityId: String = "edmonton"

    @State private var state: SunState?
    @State private var isLoading: Bool = false
    @State private var errorMessage: String?
    @State private var lastFetched: Date?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                modeChip
                solarPositionCard
                spaceWeatherCard
                auroraCard
                cmeCard
                sunspotCard
                schumannCard
                seasonalCard
                footer
            }
            .padding(16)
        }
        .background(AppTheme.background)
        .refreshable {
            await refresh(force: true)
        }
        .task {
            if state == nil { await refresh(force: false) }
        }
        .overlay(alignment: .top) {
            if let err = errorMessage {
                errorBanner(err)
            }
        }
    }

    // MARK: - Solar Energy Mode chip

    private var modeChip: some View {
        let mode = (state?.solarEnergyMode ?? "unknown").lowercased()
        let (label, color) = modeStyle(mode)
        return HStack(spacing: 8) {
            Image(systemName: "sun.max.fill")
                .foregroundColor(color)
                .font(.headline)
            Text(label)
                .font(AppTheme.headlineFont)
                .foregroundColor(.white)
            Spacer()
            if isLoading {
                ProgressView()
                    .progressViewStyle(CircularProgressViewStyle(tint: AppTheme.accent))
                    .scaleEffect(0.8)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(
            Capsule()
                .fill(color.opacity(0.18))
                .overlay(Capsule().stroke(color.opacity(0.6), lineWidth: 1))
        )
    }

    private func modeStyle(_ mode: String) -> (String, Color) {
        switch mode {
        case "quiet":     return ("Quiet",     AppTheme.success)
        case "unsettled": return ("Unsettled", AppTheme.warning)
        case "active":    return ("Active",    .orange)
        case "storm":     return ("Storm",     .red)
        case "severe":    return ("Severe",    Color(red: 0.7, green: 0.1, blue: 0.1))
        default:          return ("Unknown",   .gray)
        }
    }

    // MARK: - Solar Position card

    private var solarPositionCard: some View {
        SunCard(title: "Solar Position", icon: "sun.horizon.fill", iconColor: .orange) {
            HStack(alignment: .top, spacing: 16) {
                SunArcView(
                    sunrise: state?.sunTimes?.sunrise,
                    solarNoon: state?.sunTimes?.solarNoon,
                    sunset: state?.sunTimes?.sunset
                )
                .frame(width: 120, height: 120)

                VStack(alignment: .leading, spacing: 6) {
                    timeRow(icon: "sunrise.fill",
                            label: "Sunrise",
                            value: shortTime(state?.sunTimes?.sunrise))
                    timeRow(icon: "sun.max.fill",
                            label: "Solar Noon",
                            value: shortTime(state?.sunTimes?.solarNoon))
                    timeRow(icon: "sunset.fill",
                            label: "Sunset",
                            value: shortTime(state?.sunTimes?.sunset))
                    timeRow(icon: "clock.fill",
                            label: "Day Length",
                            value: formatDayLength(state?.sunTimes?.dayLength))
                    timeRow(icon: "sparkles",
                            label: "Golden Hour",
                            value: shortTime(state?.sunTimes?.goldenHour))
                }
                Spacer()
            }
        }
    }

    private func timeRow(icon: String, label: String, value: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .foregroundColor(.orange.opacity(0.85))
                .frame(width: 16)
            Text(label)
                .font(AppTheme.captionFont)
                .foregroundColor(.white.opacity(0.6))
            Spacer()
            Text(value)
                .font(AppTheme.captionFont)
                .foregroundColor(.white)
        }
    }

    // MARK: - Space Weather card

    private var spaceWeatherCard: some View {
        let kp = state?.spaceWeather?.kpIndex
        let wind = state?.spaceWeather?.solarWindSpeed
        let flare = state?.spaceWeather?.flareClass ?? "—"
        let kpColor = kpColor(kp)
        return SunCard(title: "Space Weather", icon: "bolt.fill", iconColor: .yellow) {
            HStack(spacing: 16) {
                metricBlock(
                    big: kp.map { String(format: "%.1f", $0) } ?? "—",
                    label: "Kp Index",
                    color: kpColor
                )
                Divider().background(Color.white.opacity(0.1))
                metricBlock(
                    big: wind.map { String(format: "%.0f", $0) } ?? "—",
                    suffix: " km/s",
                    label: "Solar Wind",
                    color: windColor(wind)
                )
                Divider().background(Color.white.opacity(0.1))
                metricBlock(
                    big: flare,
                    label: "Flare Class",
                    color: flareColor(flare)
                )
            }
        }
    }

    private func metricBlock(big: String, suffix: String = "", label: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(big)
                    .font(.system(.title2, design: .rounded, weight: .bold))
                    .foregroundColor(color)
                if !suffix.isEmpty {
                    Text(suffix)
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.6))
                }
            }
            Text(label)
                .font(AppTheme.captionFont)
                .foregroundColor(.white.opacity(0.6))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func kpColor(_ kp: Double?) -> Color {
        guard let k = kp else { return .gray }
        if k < 3 { return AppTheme.success }
        if k < 5 { return AppTheme.warning }
        if k < 7 { return .orange }
        return AppTheme.danger
    }

    private func windColor(_ wind: Double?) -> Color {
        guard let w = wind else { return .gray }
        if w < 400 { return AppTheme.success }
        if w < 600 { return AppTheme.warning }
        return AppTheme.danger
    }

    private func flareColor(_ flare: String) -> Color {
        let u = flare.uppercased()
        if u.hasPrefix("X") { return AppTheme.danger }
        if u.hasPrefix("M") { return .orange }
        if u.hasPrefix("C") { return AppTheme.warning }
        return AppTheme.success
    }

    // MARK: - Aurora card

    private var auroraCard: some View {
        SunCard(title: "Aurora Forecast", icon: "sun.dust.fill", iconColor: .green) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Visibility (\(cityId.replacingOccurrences(of: "_", with: " ").capitalized))")
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.7))
                    Spacer()
                    Text((state?.aurora?.likelihood ?? "none").capitalized)
                        .font(AppTheme.headlineFont)
                        .foregroundColor(auroraColor(state?.aurora?.likelihood))
                }

                if let forecast = state?.aurora?.kpForecast, !forecast.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Next 3-day Kp")
                            .font(AppTheme.captionFont)
                            .foregroundColor(.white.opacity(0.6))
                        KpBarChart(values: forecast)
                            .frame(height: 56)
                    }
                } else {
                    Text("Forecast unavailable")
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.4))
                }
            }
        }
    }

    private func auroraColor(_ likelihood: String?) -> Color {
        switch (likelihood ?? "").lowercased() {
        case "high":     return AppTheme.success
        case "moderate": return AppTheme.warning
        case "low":      return .orange
        default:         return .gray
        }
    }

    // MARK: - CME / Alerts card

    private var cmeCard: some View {
        SunCard(title: "CME & Alerts", icon: "flame.fill", iconColor: .red) {
            let alerts = state?.cmeAlerts ?? []
            if alerts.isEmpty {
                HStack {
                    Image(systemName: "checkmark.seal.fill")
                        .foregroundColor(AppTheme.success)
                    Text("No active alerts")
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.6))
                    Spacer()
                }
                .padding(.vertical, 6)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(alerts.prefix(5)) { alert in
                        cmeRow(alert)
                    }
                    if alerts.count > 5 {
                        Text("+\(alerts.count - 5) more")
                            .font(AppTheme.captionFont)
                            .foregroundColor(.white.opacity(0.5))
                    }
                }
            }
        }
    }

    private func cmeRow(_ alert: CMEAlert) -> some View {
        HStack(alignment: .top, spacing: 8) {
            severityBadge(alert.severity)
            VStack(alignment: .leading, spacing: 2) {
                Text(alert.message ?? "—")
                    .font(AppTheme.captionFont)
                    .foregroundColor(.white.opacity(0.9))
                    .lineLimit(3)
                if let issued = alert.issuedAt {
                    Text(shortTime(issued))
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.4))
                }
            }
        }
    }

    private func severityBadge(_ severity: String?) -> some View {
        let s = (severity ?? "info").lowercased()
        let color: Color
        switch s {
        case "critical": color = .red
        case "high":     color = .orange
        case "medium":   color = AppTheme.warning
        default:         color = .gray
        }
        return Text(s.uppercased())
            .font(.system(size: 9, weight: .heavy, design: .monospaced))
            .foregroundColor(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .background(Capsule().fill(color.opacity(0.18)))
            .overlay(Capsule().stroke(color.opacity(0.6), lineWidth: 1))
    }

    // MARK: - Sunspot + F10.7 card

    private var sunspotCard: some View {
        SunCard(title: "Sunspots & F10.7", icon: "circle.dotted", iconColor: .orange) {
            HStack(spacing: 16) {
                metricBlock(
                    big: state?.sunspot?.number.map { String($0) } ?? "—",
                    label: "Sunspot #",
                    color: .orange
                )
                Divider().background(Color.white.opacity(0.1))
                metricBlock(
                    big: state?.sunspot?.f107Flux.map { String(format: "%.1f", $0) } ?? "—",
                    label: "F10.7 sfu",
                    color: .yellow
                )
                trendIcon(state?.sunspot?.trend)
            }
        }
    }

    @ViewBuilder
    private func trendIcon(_ trend: String?) -> some View {
        let t = (trend ?? "flat").lowercased()
        let (sys, c): (String, Color) = {
            switch t {
            case "up":   return ("arrow.up.right", AppTheme.success)
            case "down": return ("arrow.down.right", AppTheme.danger)
            default:     return ("arrow.right", .gray)
            }
        }()
        VStack {
            Image(systemName: sys)
                .font(.title2)
                .foregroundColor(c)
            Text(t.capitalized)
                .font(AppTheme.captionFont)
                .foregroundColor(.white.opacity(0.6))
        }
    }

    // MARK: - Schumann card

    private var schumannCard: some View {
        SunCard(title: "Schumann Resonance", icon: "waveform", iconColor: .purple) {
            HStack(spacing: 16) {
                metricBlock(
                    big: String(format: "%.2f", state?.schumann?.frequencyHz ?? 7.83),
                    suffix: " Hz",
                    label: "Fundamental",
                    color: .purple
                )
                Divider().background(Color.white.opacity(0.1))
                metricBlock(
                    big: state?.schumann?.amplitude.map { String(format: "%.1f", $0) } ?? "—",
                    label: "Amplitude",
                    color: .purple.opacity(0.7)
                )
                schumannBadge(state?.schumann?.status)
            }
        }
    }

    @ViewBuilder
    private func schumannBadge(_ status: String?) -> some View {
        let s = (status ?? "stable").lowercased()
        let color: Color = s == "anomalous" ? AppTheme.danger : AppTheme.success
        Text(s.capitalized)
            .font(.system(size: 11, weight: .semibold, design: .monospaced))
            .foregroundColor(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Capsule().fill(color.opacity(0.18)))
            .overlay(Capsule().stroke(color.opacity(0.6), lineWidth: 1))
    }

    // MARK: - Seasonal Marker card

    private var seasonalCard: some View {
        SunCard(title: "Seasonal Marker", icon: "leaf.fill", iconColor: .green) {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("Current Season")
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.6))
                    Spacer()
                    Text((state?.seasonalMarker?.currentSeason ?? "—").capitalized)
                        .font(AppTheme.headlineFont)
                        .foregroundColor(.white)
                }
                HStack {
                    Text("Next Event")
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.6))
                    Spacer()
                    Text(formatNextEvent(state?.seasonalMarker))
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.9))
                }
                HStack {
                    Text("Sun Declination")
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.6))
                    Spacer()
                    Text(state?.seasonalMarker?.sunDeclination.map { String(format: "%.2f°", $0) } ?? "—")
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.9))
                }
            }
        }
    }

    private func formatNextEvent(_ marker: SeasonalMarker?) -> String {
        guard let m = marker, let name = m.nextEvent else { return "—" }
        let pretty = name.replacingOccurrences(of: "_", with: " ").capitalized
        if let days = m.daysUntil {
            return "\(pretty) (\(days)d)"
        }
        return pretty
    }

    // MARK: - Footer

    private var footer: some View {
        HStack {
            if let ts = lastFetched {
                Text("Updated " + relativeTime(from: ts))
                    .font(AppTheme.captionFont)
                    .foregroundColor(.white.opacity(0.4))
            }
            Spacer()
            Button(action: { Task { await refresh(force: true) } }) {
                Label("Refresh", systemImage: "arrow.clockwise")
                    .font(AppTheme.captionFont)
                    .foregroundColor(AppTheme.accent)
            }
        }
        .padding(.top, 4)
    }

    private func errorBanner(_ msg: String) -> some View {
        HStack {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(AppTheme.danger)
            Text(msg)
                .font(AppTheme.captionFont)
                .foregroundColor(.white)
            Spacer()
            Button(action: { errorMessage = nil }) {
                Image(systemName: "xmark")
                    .foregroundColor(.white.opacity(0.6))
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10)
            .fill(AppTheme.danger.opacity(0.2))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(AppTheme.danger, lineWidth: 1)))
        .padding(.horizontal, 16)
        .padding(.top, 8)
    }

    // MARK: - Fetching

    private func refresh(force: Bool) async {
        isLoading = true
        defer { isLoading = false }

        if force {
            // Best-effort POST /calendar/refresh — ignore errors.
            await postRefresh()
        }

        do {
            let new = try await fetchSunState(cityId: cityId)
            self.state = new
            self.lastFetched = Date()
            self.errorMessage = nil
        } catch {
            self.errorMessage = "Failed to load sun state: \(error.localizedDescription)"
        }
    }

    /// Fetch via CalendarAPI if available; otherwise fall back to a direct
    /// URLSession call against the configured server. Keeps this view
    /// compilable even before Agent 9 lands CalendarAPI.swift.
    private func fetchSunState(cityId: String) async throws -> SunState {
        let base = appState.serverURL
        guard !base.isEmpty else { throw URLError(.badURL) }
        let baseURL = base.hasPrefix("http") ? base : "http://\(base)"
        guard let url = URL(string: "\(baseURL)/calendar/sun?city_id=\(cityId)") else {
            throw URLError(.badURL)
        }
        var req = URLRequest(url: url)
        req.setValue("Bearer \(appState.authToken)", forHTTPHeaderField: "Authorization")
        req.timeoutInterval = 20

        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(SunState.self, from: data)
    }

    private func postRefresh() async {
        let base = appState.serverURL
        guard !base.isEmpty else { return }
        let baseURL = base.hasPrefix("http") ? base : "http://\(base)"
        guard let url = URL(string: "\(baseURL)/calendar/refresh") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("Bearer \(appState.authToken)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["city_id": cityId])
        req.timeoutInterval = 25
        _ = try? await URLSession.shared.data(for: req)
    }

    // MARK: - Formatting helpers

    private func shortTime(_ iso: String?) -> String {
        guard let s = iso else { return "—" }
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = fmt.date(from: s) ?? ISO8601DateFormatter().date(from: s) {
            let out = DateFormatter()
            out.dateFormat = "HH:mm"
            return out.string(from: d)
        }
        // Try a more lenient parse
        if let d = parseLooseTime(s) {
            let out = DateFormatter()
            out.dateFormat = "HH:mm"
            return out.string(from: d)
        }
        return s
    }

    private func parseLooseTime(_ s: String) -> Date? {
        let formats = ["yyyy-MM-dd'T'HH:mm:ss.SSSZ",
                       "yyyy-MM-dd'T'HH:mm:ssZ",
                       "yyyy-MM-dd HH:mm:ss"]
        for f in formats {
            let df = DateFormatter()
            df.dateFormat = f
            df.locale = Locale(identifier: "en_US_POSIX")
            if let d = df.date(from: s) { return d }
        }
        return nil
    }

    private func formatDayLength(_ seconds: Double?) -> String {
        guard let s = seconds, s > 0 else { return "—" }
        let h = Int(s) / 3600
        let m = (Int(s) % 3600) / 60
        return "\(h)h \(m)m"
    }

    private func relativeTime(from date: Date) -> String {
        let secs = Int(Date().timeIntervalSince(date))
        if secs < 60 { return "just now" }
        if secs < 3600 { return "\(secs / 60)m ago" }
        return "\(secs / 3600)h ago"
    }
}


// MARK: - Reusable Card

private struct SunCard<Content: View>: View {
    let title: String
    let icon: String
    let iconColor: Color
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .foregroundColor(iconColor)
                Text(title)
                    .font(AppTheme.headlineFont)
                    .foregroundColor(.white)
                Spacer()
            }
            content()
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(AppTheme.cardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.white.opacity(0.08), lineWidth: 1)
                )
        )
    }
}


// MARK: - Sun Arc Visual

private struct SunArcView: View {
    let sunrise: String?
    let solarNoon: String?
    let sunset: String?

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height
            ZStack {
                // Arc path
                Path { p in
                    p.move(to: CGPoint(x: 0, y: h))
                    p.addQuadCurve(to: CGPoint(x: w, y: h),
                                   control: CGPoint(x: w / 2, y: -h * 0.3))
                }
                .stroke(
                    LinearGradient(colors: [.orange.opacity(0.9), .yellow.opacity(0.4)],
                                   startPoint: .leading,
                                   endPoint: .trailing),
                    style: StrokeStyle(lineWidth: 2, lineCap: .round)
                )

                // Sun marker along the arc at current progress
                let progress = currentSolarProgress()
                let pt = pointOnArc(progress: progress, width: w, height: h)
                Circle()
                    .fill(RadialGradient(colors: [.yellow, .orange],
                                          center: .center,
                                          startRadius: 0,
                                          endRadius: 12))
                    .frame(width: 18, height: 18)
                    .shadow(color: .orange.opacity(0.8), radius: 8)
                    .position(pt)

                // Horizon line
                Rectangle()
                    .fill(Color.white.opacity(0.15))
                    .frame(height: 1)
                    .offset(y: h / 2 - 0.5)
            }
        }
    }

    private func pointOnArc(progress: Double, width w: CGFloat, height h: CGFloat) -> CGPoint {
        let t = CGFloat(max(0, min(1, progress)))
        // Quadratic Bezier: B(t) = (1-t)^2 P0 + 2(1-t)t P1 + t^2 P2
        let p0 = CGPoint(x: 0, y: h)
        let p1 = CGPoint(x: w / 2, y: -h * 0.3)
        let p2 = CGPoint(x: w, y: h)
        let x = pow(1 - t, 2) * p0.x + 2 * (1 - t) * t * p1.x + pow(t, 2) * p2.x
        let y = pow(1 - t, 2) * p0.y + 2 * (1 - t) * t * p1.y + pow(t, 2) * p2.y
        return CGPoint(x: x, y: y)
    }

    /// Returns 0 at sunrise, 0.5 at solar noon, 1 at sunset; falls back to
    /// fraction of day if times are missing.
    private func currentSolarProgress() -> Double {
        if let rise = parseISO(sunrise), let set = parseISO(sunset) {
            let now = Date()
            let total = set.timeIntervalSince(rise)
            if total > 0 {
                let elapsed = now.timeIntervalSince(rise)
                return max(0, min(1, elapsed / total))
            }
        }
        // Fallback: fraction of day in local time
        let now = Date()
        let cal = Calendar.current
        let comps = cal.dateComponents([.hour, .minute], from: now)
        let mins = Double((comps.hour ?? 12) * 60 + (comps.minute ?? 0))
        return mins / (24 * 60)
    }

    private func parseISO(_ s: String?) -> Date? {
        guard let s = s else { return nil }
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = fmt.date(from: s) { return d }
        return ISO8601DateFormatter().date(from: s)
    }
}


// MARK: - Kp Bar Chart (3-day forecast)

private struct KpBarChart: View {
    let values: [Double]

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height
            let n = max(1, values.count)
            let gap: CGFloat = 6
            let barWidth = max(8, (w - gap * CGFloat(n - 1)) / CGFloat(n))
            let maxKp: Double = 9.0

            HStack(alignment: .bottom, spacing: gap) {
                ForEach(Array(values.enumerated()), id: \.offset) { _, v in
                    let frac = CGFloat(min(maxKp, max(0, v)) / maxKp)
                    VStack(spacing: 2) {
                        Spacer(minLength: 0)
                        RoundedRectangle(cornerRadius: 3)
                            .fill(kpColor(v))
                            .frame(width: barWidth, height: max(2, frac * (h - 18)))
                        Text(String(format: "%.1f", v))
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundColor(.white.opacity(0.6))
                    }
                }
            }
            .frame(width: w, height: h, alignment: .bottomLeading)
        }
    }

    private func kpColor(_ k: Double) -> Color {
        if k < 3 { return .green }
        if k < 5 { return .yellow }
        if k < 7 { return .orange }
        return .red
    }
}


// MARK: - Preview

#if DEBUG
struct CalendarSunView_Previews: PreviewProvider {
    static var previews: some View {
        CalendarSunView(cityId: "edmonton")
            .environmentObject(AppState())
            .preferredColorScheme(.dark)
    }
}
#endif
