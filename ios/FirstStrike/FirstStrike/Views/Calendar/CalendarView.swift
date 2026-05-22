// CalendarView.swift
// Root of the Calendar tab.
//
// Data flow:
//   1. On appear, builds a CalendarAPI from AppState's serverURL+authToken.
//   2. Calls /calendar/dashboard?city_id=... — one round trip primes events_7d/30d,
//      todos_7d/30d, moon, sun and the city list.
//   3. The 4 sub-tabs (Events / To Do / Moon / Sun) read from the primed cache.
//      Switching between 7d/30d swaps cached arrays without a re-fetch.
//   4. Pull-to-refresh on any sub-tab calls POST /calendar/refresh then re-loads
//      the dashboard.
//   5. City selection persists via @AppStorage AND POSTs /calendar/city/select.
//   6. Window choice persists via @AppStorage; default 7d, default city Edmonton.
//
// SunView is provided by Agent 10. If the symbol resolves it renders inline;
// otherwise the placeholder string "SunView()" is displayed.

import SwiftUI

struct CalendarView: View {
    @EnvironmentObject var appState: AppState

    // MARK: - Persisted user choices
    @AppStorage("calendar.selectedCity") private var selectedCityRaw: String = CalendarCity.edmonton.rawValue
    @AppStorage("calendar.windowDays") private var windowDaysRaw: Int = CalendarWindow.sevenDay.rawValue

    // MARK: - Local state
    @State private var subTab: SubTab = .events
    @State private var showingCityPicker = false

    @State private var dashboard: CalendarDashboard?
    @State private var moon: MoonState?
    @State private var isLoading = false
    @State private var errorMessage: String?

    // MARK: - Derived bindings

    private var selectedCity: Binding<CalendarCity> {
        Binding(
            get: { CalendarCity(rawValue: selectedCityRaw) ?? .edmonton },
            set: { selectedCityRaw = $0.rawValue }
        )
    }

    private var window: Binding<CalendarWindow> {
        Binding(
            get: { CalendarWindow(rawValue: windowDaysRaw) ?? .sevenDay },
            set: { windowDaysRaw = $0.rawValue }
        )
    }

    enum SubTab: String, CaseIterable, Identifiable {
        case events = "Events"
        case todos  = "To Do"
        case moon   = "Moon"
        case sun    = "Sun"
        var id: String { rawValue }

        var icon: String {
            switch self {
            case .events: return "calendar"
            case .todos:  return "checklist"
            case .moon:   return "moon.fill"
            case .sun:    return "sun.max.fill"
            }
        }
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                header
                Divider().background(.white.opacity(0.08))
                subTabBar
                if showsWindowToggle { windowBar }
                Divider().background(.white.opacity(0.08))
                content
            }
            .background(AppTheme.background.ignoresSafeArea())
            .navigationBarHidden(true)
        }
        .sheet(isPresented: $showingCityPicker) {
            CalendarCityPicker(selected: selectedCity) { newCity in
                Task { await selectCity(newCity) }
            }
        }
        .task { await loadDashboard() }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: 12) {
            Button {
                showingCityPicker = true
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "mappin.circle.fill")
                        .foregroundColor(AppTheme.accent)
                    Text(selectedCity.wrappedValue.emoji)
                    Text(selectedCity.wrappedValue.displayName)
                        .font(AppTheme.headlineFont)
                        .foregroundColor(.white)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(.white.opacity(0.6))
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(AppTheme.cardBackground)
                .clipShape(Capsule())
            }
            .buttonStyle(.plain)

            Spacer()

            Button {
                Task { await refreshAll() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(.white)
                    .padding(10)
                    .background(AppTheme.cardBackground)
                    .clipShape(Circle())
                    .opacity(isLoading ? 0.5 : 1.0)
            }
            .buttonStyle(.plain)
            .disabled(isLoading)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    private var subTabBar: some View {
        HStack(spacing: 0) {
            ForEach(SubTab.allCases) { tab in
                Button {
                    withAnimation(.easeInOut(duration: 0.18)) { subTab = tab }
                } label: {
                    VStack(spacing: 4) {
                        Image(systemName: tab.icon)
                            .font(.system(size: 13, weight: .semibold))
                        Text(tab.rawValue.uppercased())
                            .font(.system(size: 11, weight: .bold, design: .rounded))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                    .foregroundColor(subTab == tab ? AppTheme.accent : .white.opacity(0.5))
                    .background(
                        VStack {
                            Spacer()
                            Rectangle()
                                .fill(subTab == tab ? AppTheme.accent : .clear)
                                .frame(height: 2)
                        }
                    )
                }
                .buttonStyle(.plain)
            }
        }
        .background(AppTheme.background)
    }

    private var showsWindowToggle: Bool {
        subTab == .events || subTab == .todos
    }

    private var windowBar: some View {
        HStack(spacing: 8) {
            Text("Window")
                .font(AppTheme.captionFont)
                .foregroundColor(.white.opacity(0.5))
            ForEach(CalendarWindow.allCases) { opt in
                Button {
                    window.wrappedValue = opt
                } label: {
                    Text(opt.label)
                        .font(.system(size: 12, weight: .semibold))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(window.wrappedValue == opt ? AppTheme.accent : AppTheme.inputBackground)
                        .foregroundColor(window.wrappedValue == opt ? .white : .white.opacity(0.7))
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(AppTheme.background)
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        switch subTab {
        case .events:
            CalendarEventsView(
                cityID: selectedCity.wrappedValue.rawValue,
                window: window,
                events: currentEvents,
                isLoading: isLoading,
                errorMessage: errorMessage,
                onPullRefresh: { await refreshAll() }
            )
        case .todos:
            CalendarTodosView(
                cityID: selectedCity.wrappedValue.rawValue,
                window: window,
                todos: currentTodos,
                isLoading: isLoading,
                errorMessage: errorMessage,
                onPullRefresh: { await refreshAll() }
            )
        case .moon:
            CalendarMoonView(
                moon: moon,
                isLoading: isLoading,
                errorMessage: errorMessage,
                onPullRefresh: { await refreshAll() }
            )
        case .sun:
            // Agent 10's view. It owns its own loading + /calendar/sun fetch.
            CalendarSunView(cityId: selectedCity.wrappedValue.rawValue)
        }
    }

    // MARK: - Cached data

    private var currentEvents: [CalendarEvent] {
        guard let d = dashboard else { return [] }
        return (window.wrappedValue == .sevenDay ? d.events7d : d.events30d) ?? []
    }

    private var currentTodos: [CalendarTodo] {
        guard let d = dashboard else { return [] }
        return (window.wrappedValue == .sevenDay ? d.todos7d : d.todos30d) ?? []
    }

    // MARK: - Networking

    private func loadDashboard() async {
        guard let api = CalendarAPI.make(from: appState) else {
            errorMessage = "Server not configured. Set up in Settings."
            return
        }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        let cityID = selectedCity.wrappedValue.rawValue
        do {
            async let dash = api.dashboard(cityID: cityID)
            async let moonState = api.moon()
            self.dashboard = try await dash
            self.moon = (try? await moonState) ?? self.dashboard?.moon
        } catch let err as CalendarAPIError {
            errorMessage = err.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func refreshAll() async {
        guard let api = CalendarAPI.make(from: appState) else { return }
        isLoading = true
        defer { isLoading = false }
        let cityID = selectedCity.wrappedValue.rawValue
        do {
            try await api.refresh(cityID: cityID)
        } catch {
            // Refresh is best-effort; still re-pull dashboard.
        }
        await loadDashboard()
    }

    private func selectCity(_ city: CalendarCity) async {
        guard let api = CalendarAPI.make(from: appState) else { return }
        do { try await api.selectCity(city.rawValue) } catch { /* persist locally anyway */ }
        await loadDashboard()
    }
}
