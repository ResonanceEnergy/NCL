import Foundation

// MARK: - Wave 14I item 10 — Capital rotation data models
//
// Mirrors the JSON shape returned by GET /intelligence/rotation. Three
// nested blocks (rotation / style_ratios / cycle_phase) — each independently
// fallable on the server side, so the iOS view tolerates nil sub-blocks.

struct RotationEnvelope: Decodable {
    let date: String?
    let rotation: RotationSnapshot?
    let styleRatios: StyleSnapshot?
    let cyclePhase: CycleSnapshot?

    enum CodingKeys: String, CodingKey {
        case date
        case rotation
        case styleRatios = "style_ratios"
        case cyclePhase = "cycle_phase"
    }
}

struct RotationSnapshot: Decodable {
    let date: String?
    let benchmark: String?
    let benchmarkLast: Double?
    let breadth: BreadthBlock?
    let byQuadrant: [String: [String]]?
    let sectors: [SectorPoint]
    let leadershipSummary: String?

    enum CodingKeys: String, CodingKey {
        case date
        case benchmark
        case benchmarkLast = "benchmark_last"
        case breadth
        case byQuadrant = "by_quadrant"
        case sectors
        case leadershipSummary = "leadership_summary"
    }
}

struct BreadthBlock: Decodable {
    let sectorsAboveSma: Int?
    let sectorsEvaluated: Int?
    let pct: Double?
    let regime: String?

    enum CodingKeys: String, CodingKey {
        case sectorsAboveSma = "sectors_above_50d_sma"
        case sectorsEvaluated = "sectors_evaluated"
        case pct
        case regime
    }
}

struct SectorPoint: Decodable, Identifiable {
    var id: String { symbol }
    let symbol: String
    let label: String
    let last: Double?
    let dayPct: Double?
    let aboveSma: Bool?
    let ratioPctChg20d: Double?
    let rsMomentum5d: Double?
    let quadrant: String?
    let relativeStrength: Double?

    enum CodingKeys: String, CodingKey {
        case symbol
        case label
        case last
        case dayPct = "day_pct"
        case aboveSma = "above_50d_sma"
        case ratioPctChg20d = "ratio_pct_chg_20d"
        case rsMomentum5d = "rs_momentum_5d"
        case quadrant
        case relativeStrength = "relative_strength"
    }
}

struct StyleSnapshot: Decodable {
    let date: String?
    let ratios: [StyleRatio]
    let regimeSignals: [String]?

    enum CodingKeys: String, CodingKey {
        case date
        case ratios
        case regimeSignals = "regime_signals"
    }
}

struct StyleRatio: Decodable, Identifiable {
    var id: String { ratio }
    let ratio: String
    let label: String?
    let interpretation: String?
    let last: Double?
    let dayPct: Double?
    let fiveDayPct: Double?
    let twentyDayPct: Double?
    let direction: String?

    enum CodingKeys: String, CodingKey {
        case ratio
        case label
        case interpretation
        case last
        case dayPct = "day_pct"
        case fiveDayPct = "5d_pct"
        case twentyDayPct = "20d_pct"
        case direction
    }
}

struct CycleSnapshot: Decodable {
    let date: String?
    let classification: CycleClassification?
    let indicators: CycleIndicators?
}

struct CycleClassification: Decodable {
    let phase: String?
    let confidence: Double?
    let votes: [String: Int]?
    let reasons: [String]?
    let expectedLeaders: [String]?

    enum CodingKeys: String, CodingKey {
        case phase
        case confidence
        case votes
        case reasons
        case expectedLeaders = "expected_leaders"
    }
}

struct CycleIndicators: Decodable {
    // Loose — we don't render these in v1 widget; reserved for future detail view.
    let yieldCurve: [String: AnyCodable]?
    let pmi: [String: AnyCodable]?
    let joblessClaims: [String: AnyCodable]?
    let creditSpread: [String: AnyCodable]?

    enum CodingKeys: String, CodingKey {
        case yieldCurve = "yield_curve"
        case pmi
        case joblessClaims = "jobless_claims"
        case creditSpread = "credit_spread"
    }
}
