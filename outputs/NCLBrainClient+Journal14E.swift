import Foundation

// MARK: - NCLBrainClient Journal+LifePlan Extension (Wave 14E)
//
// Backend endpoints shipped in NCL d8d7991. See
// docs/JOURNAL_REDESIGN_2026-05-25.md for design.

@MainActor
extension NCLBrainClient {

    // MARK: Morning Quiz

    /// Submit today's morning quiz. Returns the quiz_id on success.
    func submitMorningQuiz(
        moodScore: Int,
        moodWord: String,
        topPriority: String,
        supportingTasks: [String],
        marketPosture: String,
        researchQuestion: String,
        gratitude: String,
        yesterdayLesson: String,
        notes: String,
        wisdomIDShown: String
    ) async throws -> [String: Any] {
        let body: [String: Any] = [
            "mood_score": moodScore,
            "mood_word": moodWord,
            "top_priority": topPriority,
            "supporting_tasks": supportingTasks,
            "market_posture": marketPosture,
            "research_question": researchQuestion,
            "gratitude": gratitude,
            "yesterday_lesson": yesterdayLesson,
            "notes": notes,
            "wisdom_id_shown": wisdomIDShown,
        ]
        let result = try await executeCommand(
            endpoint: "/journal/morning-quiz",
            method: "POST",
            body: body
        )
        return result
    }

    /// Today's quiz if it exists.
    func fetchMorningQuizToday() async throws -> MorningQuiz? {
        let result = try await executeCommand(
            endpoint: "/journal/morning-quiz/today",
            method: "GET"
        )
        guard let q = result["quiz"] as? [String: Any] else { return nil }
        return MorningQuiz(from: q)
    }

    /// Most recent quiz (today preferred, else newest).
    func fetchMorningQuizLatest() async throws -> MorningQuiz? {
        let result = try await executeCommand(
            endpoint: "/journal/morning-quiz/latest",
            method: "GET"
        )
        guard let q = result["quiz"] as? [String: Any] else { return nil }
        return MorningQuiz(from: q)
    }

    /// History list.
    func fetchMorningQuizHistory(limit: Int = 30) async throws -> [MorningQuizHistoryItem] {
        let result = try await executeCommand(
            endpoint: "/journal/morning-quiz/history?limit=\(limit)",
            method: "GET"
        )
        let items = result["items"] as? [[String: Any]] ?? []
        return items.compactMap { MorningQuizHistoryItem(from: $0) }
    }

    // MARK: Life Plan

    func fetchLifeDashboard() async throws -> LifeDashboard {
        let result = try await executeCommand(
            endpoint: "/life/dashboard",
            method: "GET"
        )
        return LifeDashboard(from: result)
    }

    func fetchVision() async throws -> Vision? {
        let result = try await executeCommand(endpoint: "/life/vision", method: "GET")
        guard let v = result["vision"] as? [String: Any] else { return nil }
        return Vision(from: v)
    }

    func setVision(title: String, narrative: String, horizonYears: Int, pillars: [String]) async throws -> Vision? {
        let body: [String: Any] = [
            "title": title,
            "narrative": narrative,
            "horizon_years": horizonYears,
            "pillars": pillars,
        ]
        let result = try await executeCommand(endpoint: "/life/vision", method: "POST", body: body)
        guard let v = result["vision"] as? [String: Any] else { return nil }
        return Vision(from: v)
    }

    func fetchCurrentNorthStar() async throws -> NorthStar? {
        let result = try await executeCommand(endpoint: "/life/north-star/current", method: "GET")
        guard let n = result["north_star"] as? [String: Any] else { return nil }
        return NorthStar(from: n)
    }

    func fetchGoals(scope: String? = nil, status: String? = nil) async throws -> [LifeGoal] {
        var ep = "/life/goals"
        var qs: [String] = []
        if let s = scope { qs.append("scope=\(s)") }
        if let st = status { qs.append("status=\(st)") }
        if !qs.isEmpty { ep += "?" + qs.joined(separator: "&") }
        let result = try await executeCommand(endpoint: ep, method: "GET")
        let arr = result["goals"] as? [[String: Any]] ?? []
        return arr.compactMap { LifeGoal(from: $0) }
    }

    func fetchPlans(kind: String? = nil) async throws -> [LifePlan] {
        var ep = "/life/plans"
        if let k = kind { ep += "?kind=\(k)" }
        let result = try await executeCommand(endpoint: ep, method: "GET")
        let arr = result["plans"] as? [[String: Any]] ?? []
        return arr.compactMap { LifePlan(from: $0) }
    }

    func fetchWisdomToday(category: String? = nil) async throws -> DailyWisdom? {
        var ep = "/life/wisdom/today"
        if let c = category { ep += "?category=\(c)" }
        let result = try await executeCommand(endpoint: ep, method: "GET")
        guard let w = result["wisdom"] as? [String: Any] else { return nil }
        return DailyWisdom(from: w)
    }
}
