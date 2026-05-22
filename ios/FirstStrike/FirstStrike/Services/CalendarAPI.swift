// CalendarAPI.swift
// Async/await client for the NCL Brain Calendar endpoints (port 8800).
// Uses URLSession + the bearer token from AppState.authToken.
// All methods throw CalendarAPIError; callers should catch and display.

import Foundation

enum CalendarWindow: Int, Codable, CaseIterable, Identifiable {
    case sevenDay = 7
    case thirtyDay = 30

    var id: Int { rawValue }
    var label: String { rawValue == 7 ? "7 day" : "30 day" }
}

enum CalendarAPIError: LocalizedError {
    case notConfigured
    case badURL
    case http(Int, String?)
    case decoding(Error)
    case transport(Error)

    var errorDescription: String? {
        switch self {
        case .notConfigured:        return "Server URL or auth token not configured."
        case .badURL:               return "Invalid URL."
        case .http(let code, let body):
            return "HTTP \(code)\(body.map { " — \($0)" } ?? "")"
        case .decoding(let err):    return "Decode error: \(err.localizedDescription)"
        case .transport(let err):   return "Network error: \(err.localizedDescription)"
        }
    }
}

/// Thin wrapper around URLSession. Holds no state itself — the caller (CalendarView)
/// constructs one with the live serverURL + authToken from AppState.
struct CalendarAPI {
    let baseURL: String
    let authToken: String
    let session: URLSession

    init(baseURL: String, authToken: String, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.authToken = authToken
        self.session = session
    }

    /// Build a CalendarAPI from current AppState. Returns nil if not configured.
    @MainActor
    static func make(from appState: AppState) -> CalendarAPI? {
        guard !appState.serverURL.isEmpty, !appState.authToken.isEmpty else { return nil }
        let url = appState.serverURL.hasPrefix("http")
            ? appState.serverURL
            : "http://\(appState.serverURL)"
        return CalendarAPI(baseURL: url, authToken: appState.authToken)
    }

    // MARK: - Public API

    func dashboard(cityID: String) async throws -> CalendarDashboard {
        try await get("/calendar/dashboard", query: ["city_id": cityID])
    }

    func events(cityID: String, window: CalendarWindow) async throws -> [CalendarEvent] {
        let envelope: EventsEnvelope = try await get(
            "/calendar/events/compiled",
            query: ["city_id": cityID, "window": String(window.rawValue)]
        )
        return envelope.events
    }

    func todos(cityID: String, window: CalendarWindow) async throws -> [CalendarTodo] {
        let envelope: TodosEnvelope = try await get(
            "/calendar/todos",
            query: ["city_id": cityID, "window": String(window.rawValue)]
        )
        return envelope.todos
    }

    func moon() async throws -> MoonState {
        try await get("/calendar/moon", query: [:])
    }

    // Note: /calendar/sun is fetched directly by CalendarSunView (Agent 10) since
    // the SunState schema (space weather, aurora, CMEs, etc.) is owned there.

    func selectCity(_ cityID: String) async throws {
        let _: EmptyResponse = try await post("/calendar/city/select", body: ["city_id": cityID])
    }

    func refresh(cityID: String) async throws {
        let _: EmptyResponse = try await post("/calendar/refresh", body: ["city_id": cityID])
    }

    // MARK: - Internals

    private func get<T: Decodable>(_ path: String, query: [String: String]) async throws -> T {
        guard var components = URLComponents(string: baseURL + path) else { throw CalendarAPIError.badURL }
        if !query.isEmpty {
            components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        guard let url = components.url else { throw CalendarAPIError.badURL }
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        return try await execute(req)
    }

    private func post<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        guard let url = URL(string: baseURL + path) else { throw CalendarAPIError.badURL }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await execute(req)
    }

    private func execute<T: Decodable>(_ req: URLRequest) async throws -> T {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            throw CalendarAPIError.transport(error)
        }
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            let body = String(data: data, encoding: .utf8)
            throw CalendarAPIError.http(http.statusCode, body)
        }
        // Empty-body POST endpoints decode into EmptyResponse.
        if T.self == EmptyResponse.self {
            return EmptyResponse() as! T
        }
        do {
            return try Self.decoder.decode(T.self, from: data)
        } catch {
            throw CalendarAPIError.decoding(error)
        }
    }

    /// Shared decoder: tolerates both ISO8601 with and without fractional seconds.
    static let decoder: JSONDecoder = {
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .custom { decoder in
            let c = try decoder.singleValueContainer()
            let s = try c.decode(String.self)
            if let d = ISO8601DateFormatter.calendarFormatter.date(from: s) { return d }
            let basic = ISO8601DateFormatter()
            basic.formatOptions = [.withInternetDateTime]
            if let d = basic.date(from: s) { return d }
            // Fallback: yyyy-MM-dd
            let df = DateFormatter()
            df.dateFormat = "yyyy-MM-dd"
            df.timeZone = TimeZone(identifier: "UTC")
            if let d = df.date(from: s) { return d }
            throw DecodingError.dataCorruptedError(in: c, debugDescription: "Unrecognized date: \(s)")
        }
        return dec
    }()

    // MARK: - Envelopes

    private struct EventsEnvelope: Decodable {
        let events: [CalendarEvent]
        enum CodingKeys: String, CodingKey { case events, results, items }
        init(from decoder: Decoder) throws {
            // Backend may return {events:[...]}, {results:[...]}, or a bare array.
            if let single = try? decoder.singleValueContainer(),
               let arr = try? single.decode([CalendarEvent].self) {
                self.events = arr; return
            }
            let c = try decoder.container(keyedBy: CodingKeys.self)
            self.events = (try? c.decode([CalendarEvent].self, forKey: .events))
                ?? (try? c.decode([CalendarEvent].self, forKey: .results))
                ?? (try? c.decode([CalendarEvent].self, forKey: .items))
                ?? []
        }
    }

    private struct TodosEnvelope: Decodable {
        let todos: [CalendarTodo]
        enum CodingKeys: String, CodingKey { case todos, results, items, watchlist }
        init(from decoder: Decoder) throws {
            if let single = try? decoder.singleValueContainer(),
               let arr = try? single.decode([CalendarTodo].self) {
                self.todos = arr; return
            }
            let c = try decoder.container(keyedBy: CodingKeys.self)
            self.todos = (try? c.decode([CalendarTodo].self, forKey: .todos))
                ?? (try? c.decode([CalendarTodo].self, forKey: .results))
                ?? (try? c.decode([CalendarTodo].self, forKey: .items))
                ?? (try? c.decode([CalendarTodo].self, forKey: .watchlist))
                ?? []
        }
    }

    private struct EmptyResponse: Decodable {}
}
