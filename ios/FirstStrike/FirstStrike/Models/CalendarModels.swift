// CalendarModels.swift
// Codable models for the NCL Brain Calendar API (port 8800).
// Mirrors the schemas served by Agent 6's /calendar/* endpoints.
// All fields default to nil where the backend may omit them so the iOS app
// stays decode-tolerant if the backend evolves.

import Foundation
import SwiftUI

// MARK: - Cities

/// One of the 7 cities NCL tracks for local events. The raw value matches the
/// `city_id` the backend expects.
enum CalendarCity: String, CaseIterable, Identifiable, Codable {
    case edmonton
    case calgary
    case panama_city
    case san_salvador
    case montevideo
    case asuncion
    case oaxaca

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .edmonton:      return "Edmonton"
        case .calgary:       return "Calgary"
        case .panama_city:   return "Panama City"
        case .san_salvador:  return "San Salvador"
        case .montevideo:    return "Montevideo"
        case .asuncion:      return "Asuncion"
        case .oaxaca:        return "Oaxaca"
        }
    }

    var country: String {
        switch self {
        case .edmonton, .calgary:     return "Canada"
        case .panama_city:            return "Panama"
        case .san_salvador:           return "El Salvador"
        case .montevideo:             return "Uruguay"
        case .asuncion:               return "Paraguay"
        case .oaxaca:                 return "Mexico"
        }
    }

    var emoji: String {
        switch self {
        case .edmonton, .calgary:     return "🇨🇦"
        case .panama_city:            return "🇵🇦"
        case .san_salvador:           return "🇸🇻"
        case .montevideo:             return "🇺🇾"
        case .asuncion:               return "🇵🇾"
        case .oaxaca:                 return "🇲🇽"
        }
    }
}

struct CityMeta: Codable, Identifiable, Hashable {
    let id: String              // city_id
    let name: String
    let country: String?
    let timezone: String?
    let lat: Double?
    let lon: Double?

    enum CodingKeys: String, CodingKey {
        case id = "city_id"
        case name
        case country
        case timezone
        case lat
        case lon
    }
}

// MARK: - Events

struct CalendarEvent: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let description: String?
    let date: Date              // event date (UTC midnight or ISO timestamp)
    let endDate: Date?
    let category: String?       // market | local | intel | etc.
    let source: String?         // prediction | council | scanner | portfolio | intel | market | local | cross
    let impact: String?         // low | medium | high | critical
    let cityID: String?
    let url: String?
    let tags: [String]?
    let metadata: [String: AnyCodableValue]?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case description
        case date
        case endDate = "end_date"
        case category
        case source
        case impact
        case cityID = "city_id"
        case url
        case tags
        case metadata
    }

    var impactColor: Color {
        switch (impact ?? "").lowercased() {
        case "critical": return .red
        case "high":     return .orange
        case "medium":   return .yellow
        case "low":      return .green
        default:         return .gray
        }
    }

    var sourceColor: Color {
        switch (source ?? "").lowercased() {
        case "prediction": return .purple
        case "council":    return AppTheme.claude
        case "scanner":    return AppTheme.grok
        case "portfolio":  return AppTheme.gemini
        case "intel":      return AppTheme.accent
        case "market":     return .blue
        case "local":      return .teal
        case "cross":      return .pink
        default:           return .gray
        }
    }

    var sourceIcon: String {
        switch (source ?? "").lowercased() {
        case "prediction": return "wand.and.stars"
        case "council":    return "person.3.fill"
        case "scanner":    return "antenna.radiowaves.left.and.right"
        case "portfolio":  return "chart.line.uptrend.xyaxis"
        case "intel":      return "brain.head.profile"
        case "market":     return "dollarsign.circle.fill"
        case "local":      return "mappin.and.ellipse"
        case "cross":      return "link"
        default:           return "circle.fill"
        }
    }
}

// MARK: - Todos

struct CalendarTodo: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let detail: String?
    let priority: Int           // 1-10 (matches AppTheme.priorityColor)
    let dueDate: Date?
    let source: String?         // moon | prediction | scanner | council | journal | portfolio | paper | calendar
    let energyAligned: Bool?
    let category: String?
    let url: String?
    let tags: [String]?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case detail
        case priority
        case dueDate = "due_date"
        case source
        case energyAligned = "energy_aligned"
        case category
        case url
        case tags
    }
}

// MARK: - Moon

struct MoonPhase: Codable, Hashable {
    let name: String                // "Waxing Crescent" etc.
    let illumination: Double?       // 0.0-1.0
    let age: Double?                // days into 29.5-day cycle
    let angle: Double?              // 0-360
    let nextMajor: String?          // "Full Moon"
    let nextMajorDate: Date?

    enum CodingKeys: String, CodingKey {
        case name
        case illumination
        case age
        case angle
        case nextMajor = "next_major"
        case nextMajorDate = "next_major_date"
    }

    /// SF Symbol for the current phase. Falls back to `moon` if unknown.
    var icon: String {
        let n = name.lowercased()
        if n.contains("waxing crescent") { return "moonphase.waxing.crescent" }
        if n.contains("waxing gibbous")  { return "moonphase.waxing.gibbous" }
        if n.contains("waning crescent") { return "moonphase.waning.crescent" }
        if n.contains("waning gibbous")  { return "moonphase.waning.gibbous" }
        if n.contains("first quarter")   { return "moonphase.first.quarter" }
        if n.contains("last quarter") || n.contains("third quarter") {
            return "moonphase.last.quarter"
        }
        if n.contains("full") { return "moonphase.full.moon" }
        if n.contains("new")  { return "moonphase.new.moon" }
        return "moon.fill"
    }
}

struct MoonState: Codable {
    let phase: MoonPhase
    let energy: String?             // e.g. "Releasing", "Building"
    let cycleContext: String?       // free-form narrative
    let upcomingPhases: [UpcomingPhase]?
    let suggestedTodos: [CalendarTodo]?

    enum CodingKeys: String, CodingKey {
        case phase
        case energy
        case cycleContext = "cycle_context"
        case upcomingPhases = "upcoming_phases"
        case suggestedTodos = "suggested_todos"
    }
}

struct UpcomingPhase: Codable, Identifiable, Hashable {
    var id: String { "\(name)-\(dateISO)" }
    let name: String
    let dateISO: String             // raw ISO for stable Identifiable
    let date: Date
    let daysUntil: Int?

    enum CodingKeys: String, CodingKey {
        case name
        case date
        case daysUntil = "days_until"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.name = try c.decode(String.self, forKey: .name)
        let dateString = try c.decode(String.self, forKey: .date)
        self.dateISO = dateString
        self.date = ISO8601DateFormatter.calendarFormatter.date(from: dateString)
            ?? Date.distantFuture
        self.daysUntil = try c.decodeIfPresent(Int.self, forKey: .daysUntil)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(name, forKey: .name)
        try c.encode(dateISO, forKey: .date)
        try c.encodeIfPresent(daysUntil, forKey: .daysUntil)
    }
}

// MARK: - Sun
//
// SunState is defined by Agent 10 in Views/Calendar/CalendarSunView.swift
// (richer schema with space weather, aurora, CMEs, etc.). We don't redeclare
// it here, and our CalendarDashboard intentionally omits the `sun` field —
// CalendarSunView fetches /calendar/sun itself.

// MARK: - Dashboard

/// The aggregate the backend ships for the initial Calendar load.
/// `sun` is intentionally omitted — the Sun tab (Agent 10) fetches /calendar/sun
/// itself with its own SunState schema.
struct CalendarDashboard: Codable {
    let city: CityMeta?
    let moon: MoonState?
    let events7d: [CalendarEvent]?
    let events30d: [CalendarEvent]?
    let todos7d: [CalendarTodo]?
    let todos30d: [CalendarTodo]?
    let availableCities: [CityMeta]?

    enum CodingKeys: String, CodingKey {
        case city
        case moon
        case events7d = "events_7d"
        case events30d = "events_30d"
        case todos7d = "todos_7d"
        case todos30d = "todos_30d"
        case availableCities = "available_cities"
    }
}

// MARK: - Helpers

/// Lightweight Any-decoder for backend metadata blobs we don't have a schema for.
enum AnyCodableValue: Codable, Hashable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let b = try? c.decode(Bool.self) { self = .bool(b); return }
        if let i = try? c.decode(Int.self) { self = .int(i); return }
        if let d = try? c.decode(Double.self) { self = .double(d); return }
        if let s = try? c.decode(String.self) { self = .string(s); return }
        self = .null
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .int(let v):    try c.encode(v)
        case .double(let v): try c.encode(v)
        case .bool(let v):   try c.encode(v)
        case .null:          try c.encodeNil()
        }
    }
}

extension ISO8601DateFormatter {
    /// Single shared formatter that accepts fractional seconds OR plain ISO.
    static let calendarFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
}
