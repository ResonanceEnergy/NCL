import Foundation

// MARK: - Morning Quiz Model
//
// Mirrors the backend MorningQuiz schema (runtime/journal/morning_quiz.py).
// Wave 14E (2026-05-25): keystone of the Journal redesign — daily
// 7-question intention setting that propagates to working_context,
// calendar todos, and the reflection engine.

enum MarketPosture: String, CaseIterable, Identifiable {
    case aggressive
    case neutral
    case defensive
    case cash

    var id: String { rawValue }
    var label: String { rawValue.uppercased() }
}

struct MorningQuiz: Identifiable, Hashable {
    let quizID: String
    let date: String
    let submittedAt: String
    var moodScore: Int
    var moodWord: String
    var topPriority: String
    var supportingTasks: [String]
    var marketPosture: String
    var researchQuestion: String
    var gratitude: String
    var yesterdayLesson: String
    var notes: String
    let journalEntryID: String
    let lessonEntryID: String
    let pushedToWorkingContext: Bool
    let pushedToCalendarTodos: Bool
    let wisdomIDShown: String

    var id: String { quizID }

    init?(from raw: [String: Any]) {
        guard let quizID = raw["quiz_id"] as? String,
              let date = raw["date"] as? String,
              let moodScore = raw["mood_score"] as? Int,
              let topPriority = raw["top_priority"] as? String
        else { return nil }
        self.quizID = quizID
        self.date = date
        self.submittedAt = raw["submitted_at"] as? String ?? ""
        self.moodScore = moodScore
        self.moodWord = raw["mood_word"] as? String ?? ""
        self.topPriority = topPriority
        self.supportingTasks = raw["supporting_tasks"] as? [String] ?? []
        self.marketPosture = raw["market_posture"] as? String ?? "neutral"
        self.researchQuestion = raw["research_question"] as? String ?? ""
        self.gratitude = raw["gratitude"] as? String ?? ""
        self.yesterdayLesson = raw["yesterday_lesson"] as? String ?? ""
        self.notes = raw["notes"] as? String ?? ""
        self.journalEntryID = raw["journal_entry_id"] as? String ?? ""
        self.lessonEntryID = raw["lesson_entry_id"] as? String ?? ""
        self.pushedToWorkingContext = raw["pushed_to_working_context"] as? Bool ?? false
        self.pushedToCalendarTodos = raw["pushed_to_calendar_todos"] as? Bool ?? false
        self.wisdomIDShown = raw["wisdom_id_shown"] as? String ?? ""
    }
}

struct MorningQuizHistoryItem: Identifiable, Hashable {
    let quizID: String
    let date: String
    let moodScore: Int
    let moodWord: String
    let topPriority: String
    let marketPosture: String

    var id: String { quizID }

    init?(from raw: [String: Any]) {
        guard let quizID = raw["quiz_id"] as? String,
              let date = raw["date"] as? String,
              let topPriority = raw["top_priority"] as? String
        else { return nil }
        self.quizID = quizID
        self.date = date
        self.moodScore = raw["mood_score"] as? Int ?? 0
        self.moodWord = raw["mood_word"] as? String ?? ""
        self.topPriority = topPriority
        self.marketPosture = raw["market_posture"] as? String ?? "neutral"
    }
}

// MARK: - Life Plan Models

struct Vision: Hashable {
    let visionID: String
    let title: String
    let narrative: String
    let horizonYears: Int
    let pillars: [String]

    init?(from raw: [String: Any]) {
        guard let id = raw["vision_id"] as? String,
              let title = raw["title"] as? String else { return nil }
        self.visionID = id
        self.title = title
        self.narrative = raw["narrative"] as? String ?? ""
        self.horizonYears = raw["horizon_years"] as? Int ?? 10
        self.pillars = raw["pillars"] as? [String] ?? []
    }
}

struct NorthStar: Hashable {
    let starID: String
    let year: Int
    let title: String
    let measurable: String
    let why: String

    init?(from raw: [String: Any]) {
        guard let id = raw["star_id"] as? String,
              let year = raw["year"] as? Int,
              let title = raw["title"] as? String else { return nil }
        self.starID = id
        self.year = year
        self.title = title
        self.measurable = raw["measurable"] as? String ?? ""
        self.why = raw["why"] as? String ?? ""
    }
}

struct LifeGoal: Identifiable, Hashable {
    let goalID: String
    let scope: String
    let objective: String
    let status: String
    let confidence: Int
    let startsAt: String
    let endsAt: String
    let keyResults: [KeyResult]

    var id: String { goalID }

    init?(from raw: [String: Any]) {
        guard let id = raw["goal_id"] as? String,
              let objective = raw["objective"] as? String else { return nil }
        self.goalID = id
        self.scope = raw["scope"] as? String ?? "quarter"
        self.objective = objective
        self.status = raw["status"] as? String ?? "active"
        self.confidence = raw["confidence"] as? Int ?? 7
        self.startsAt = raw["starts_at"] as? String ?? ""
        self.endsAt = raw["ends_at"] as? String ?? ""
        if let krs = raw["key_results"] as? [[String: Any]] {
            self.keyResults = krs.compactMap { KeyResult(from: $0) }
        } else {
            self.keyResults = []
        }
    }
}

struct KeyResult: Identifiable, Hashable {
    let krID: String
    let description: String
    let target: Double
    let current: Double
    let unit: String

    var id: String { krID }
    var progressPct: Double { target == 0 ? 0 : min(100, max(0, current / target * 100)) }

    init?(from raw: [String: Any]) {
        guard let id = raw["kr_id"] as? String,
              let desc = raw["description"] as? String else { return nil }
        self.krID = id
        self.description = desc
        self.target = (raw["target"] as? Double) ?? (raw["target"] as? NSNumber)?.doubleValue ?? 0
        self.current = (raw["current"] as? Double) ?? (raw["current"] as? NSNumber)?.doubleValue ?? 0
        self.unit = raw["unit"] as? String ?? ""
    }
}

struct LifePlan: Identifiable, Hashable {
    let planID: String
    let title: String
    let kind: String
    let targetDate: String
    let budgetUSD: Double?
    let status: String
    let narrative: String

    var id: String { planID }

    init?(from raw: [String: Any]) {
        guard let id = raw["plan_id"] as? String,
              let title = raw["title"] as? String else { return nil }
        self.planID = id
        self.title = title
        self.kind = raw["kind"] as? String ?? "project"
        self.targetDate = raw["target_date"] as? String ?? ""
        self.budgetUSD = (raw["budget_usd"] as? Double) ?? (raw["budget_usd"] as? NSNumber)?.doubleValue
        self.status = raw["status"] as? String ?? "planning"
        self.narrative = raw["narrative"] as? String ?? ""
    }
}

struct DailyWisdom: Hashable {
    let id: String
    let category: String
    let text: String
    let source: String
    let seenCount: Int

    init?(from raw: [String: Any]) {
        guard let id = raw["id"] as? String,
              let text = raw["text"] as? String else { return nil }
        self.id = id
        self.category = raw["category"] as? String ?? "stoic"
        self.text = text
        self.source = raw["source"] as? String ?? ""
        self.seenCount = raw["seen_count"] as? Int ?? 0
    }
}

struct LifeDashboard {
    let vision: Vision?
    let northStar: NorthStar?
    let activeGoalsCount: Int
    let activeJourneysCount: Int
    let planningPlansCount: Int
    let activePlansCount: Int
    let wisdomToday: DailyWisdom?

    init(from raw: [String: Any]) {
        self.vision = (raw["vision"] as? [String: Any]).flatMap { Vision(from: $0) }
        self.northStar = (raw["north_star"] as? [String: Any]).flatMap { NorthStar(from: $0) }
        self.activeGoalsCount = raw["active_goals_count"] as? Int ?? 0
        self.activeJourneysCount = raw["active_journeys_count"] as? Int ?? 0
        self.planningPlansCount = raw["planning_plans_count"] as? Int ?? 0
        self.activePlansCount = raw["active_plans_count"] as? Int ?? 0
        self.wisdomToday = (raw["wisdom_today"] as? [String: Any]).flatMap { DailyWisdom(from: $0) }
    }
}
