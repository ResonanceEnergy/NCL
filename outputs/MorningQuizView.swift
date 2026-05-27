import SwiftUI

// MARK: - Morning Quiz View
//
// Wave 14E (2026-05-25): the daily anchor for the Journal redesign.
// 7-question intention setting; submit propagates to working_context,
// calendar todos, and the reflection engine.

struct MorningQuizView: View {
    @ObservedObject var client: NCLBrainClient

    // State
    @State private var todaysQuiz: MorningQuiz? = nil
    @State private var history: [MorningQuizHistoryItem] = []
    @State private var wisdom: DailyWisdom? = nil
    @State private var loading: Bool = false
    @State private var error: String? = nil

    // Form
    @State private var moodScore: Double = 7
    @State private var moodWord: String = ""
    @State private var topPriority: String = ""
    @State private var task1: String = ""
    @State private var task2: String = ""
    @State private var task3: String = ""
    @State private var marketPosture: String = "neutral"
    @State private var researchQuestion: String = ""
    @State private var gratitude: String = ""
    @State private var yesterdayLesson: String = ""
    @State private var notes: String = ""

    @State private var submitting: Bool = false
    @State private var submitMsg: String? = nil

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FSSpacing.lg) {
                wisdomCard
                if let q = todaysQuiz {
                    submittedCard(q)
                } else {
                    formCard
                }
                if !history.isEmpty {
                    historyStrip
                }
                if let e = error {
                    Text(e)
                        .font(FSFont.body(13))
                        .foregroundColor(FSColor.red)
                        .padding(.horizontal, FSSpacing.md)
                }
                Spacer(minLength: FSSpacing.tabBarHeight)
            }
            .padding(.horizontal, FSSpacing.md)
            .padding(.top, FSSpacing.md)
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private var wisdomCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("DAILY WISDOM")
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundColor(FSColor.cyan)
                .kerning(1.3)
            if let w = wisdom {
                Text("\u{201C}\(w.text)\u{201D}")
                    .font(FSFont.body(15))
                    .foregroundColor(FSColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Text("— \(w.source.isEmpty ? "anonymous" : w.source)")
                    .font(FSFont.body(12))
                    .foregroundColor(FSColor.textSecondary)
            } else {
                Text("Loading…")
                    .font(FSFont.body(13))
                    .foregroundColor(FSColor.textSecondary)
            }
        }
        .padding(FSSpacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FSColor.cardBg)
        .cornerRadius(8)
    }

    private var formCard: some View {
        VStack(alignment: .leading, spacing: FSSpacing.md) {
            sectionHeader("TODAY'S MORNING QUIZ")

            question("1. Mood — how am I feeling, 1–10?") {
                HStack(spacing: 12) {
                    Slider(value: $moodScore, in: 1...10, step: 1)
                    Text("\(Int(moodScore))")
                        .font(.system(size: 18, weight: .bold, design: .monospaced))
                        .foregroundColor(FSColor.orange)
                        .frame(width: 32)
                }
                TextField("one-word descriptor (focused / tired / sharp …)", text: $moodWord)
                    .textFieldStyle(.roundedBorder)
                    .autocapitalization(.none)
            }

            question("2. TOP PRIORITY — the #1 thing I MUST accomplish today") {
                TextField("Required", text: $topPriority, axis: .vertical)
                    .lineLimit(2...4)
                    .textFieldStyle(.roundedBorder)
            }

            question("3. SUPPORTING — 2-3 supporting tasks") {
                TextField("Supporting task 1", text: $task1).textFieldStyle(.roundedBorder)
                TextField("Supporting task 2", text: $task2).textFieldStyle(.roundedBorder)
                TextField("Supporting task 3", text: $task3).textFieldStyle(.roundedBorder)
            }

            question("4. MARKET POSTURE today") {
                Picker("posture", selection: $marketPosture) {
                    ForEach(MarketPosture.allCases) { p in
                        Text(p.label).tag(p.rawValue)
                    }
                }
                .pickerStyle(.segmented)
            }

            question("5. ONE QUESTION I want answered today") {
                TextField("What question?", text: $researchQuestion, axis: .vertical)
                    .lineLimit(2...3)
                    .textFieldStyle(.roundedBorder)
            }

            question("6. GRATITUDE — what am I grateful for this morning") {
                TextField("Optional but recommended", text: $gratitude, axis: .vertical)
                    .lineLimit(2...3)
                    .textFieldStyle(.roundedBorder)
            }

            question("7. YESTERDAY'S LESSON — what did I learn I don't want to forget") {
                TextField("Will be auto-saved as a Lesson", text: $yesterdayLesson, axis: .vertical)
                    .lineLimit(2...4)
                    .textFieldStyle(.roundedBorder)
            }

            question("Notes (optional)") {
                TextField("Anything else", text: $notes, axis: .vertical)
                    .lineLimit(2...5)
                    .textFieldStyle(.roundedBorder)
            }

            submitButton

            if let m = submitMsg {
                Text(m)
                    .font(FSFont.body(13))
                    .foregroundColor(m.hasPrefix("ERROR") ? FSColor.red : FSColor.green)
            }
        }
        .padding(FSSpacing.md)
        .background(FSColor.cardBg)
        .cornerRadius(8)
    }

    private var submitButton: some View {
        Button {
            Task { await submit() }
        } label: {
            HStack {
                Spacer()
                if submitting {
                    ProgressView().tint(.white)
                } else {
                    Text("SUBMIT — propagate to context + calendar + brief")
                        .font(.system(size: 13, weight: .bold, design: .monospaced))
                        .foregroundColor(.white)
                }
                Spacer()
            }
            .padding(.vertical, 12)
            .background(canSubmit ? FSColor.orange : FSColor.textSecondary)
            .cornerRadius(8)
        }
        .disabled(!canSubmit || submitting)
    }

    private var canSubmit: Bool { !topPriority.trimmingCharacters(in: .whitespaces).isEmpty }

    private func submittedCard(_ q: MorningQuiz) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                sectionHeader("SUBMITTED — \(q.date)")
                Spacer()
                Text("Mood \(q.moodScore)/10 · \(q.moodWord)")
                    .font(FSFont.body(11))
                    .foregroundColor(FSColor.textSecondary)
            }
            row("TOP PRIORITY", q.topPriority)
            if !q.supportingTasks.isEmpty {
                row("SUPPORTING", q.supportingTasks.map { "• \($0)" }.joined(separator: "\n"))
            }
            row("POSTURE", q.marketPosture.uppercased())
            if !q.researchQuestion.isEmpty { row("QUESTION", q.researchQuestion) }
            if !q.gratitude.isEmpty { row("GRATITUDE", q.gratitude) }
            if !q.yesterdayLesson.isEmpty { row("YESTERDAY", q.yesterdayLesson) }
            HStack(spacing: 6) {
                propagationChip("ctx", on: q.pushedToWorkingContext)
                propagationChip("cal", on: q.pushedToCalendarTodos)
                propagationChip("journal", on: !q.journalEntryID.isEmpty)
                propagationChip("lesson", on: !q.lessonEntryID.isEmpty)
            }
            .padding(.top, 4)
            Button { todaysQuiz = nil; preloadFormFromQuiz(q) } label: {
                Text("EDIT / RE-SUBMIT")
                    .font(.system(size: 12, weight: .bold, design: .monospaced))
                    .foregroundColor(FSColor.cyan)
            }
        }
        .padding(FSSpacing.md)
        .background(FSColor.cardBg)
        .cornerRadius(8)
    }

    private func propagationChip(_ label: String, on: Bool) -> some View {
        Text(label.uppercased())
            .font(.system(size: 10, weight: .bold, design: .monospaced))
            .foregroundColor(on ? .white : FSColor.textSecondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(on ? FSColor.green : FSColor.cardBg)
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(FSColor.textSecondary.opacity(0.4)))
            .cornerRadius(6)
    }

    private var historyStrip: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("RECENT QUIZZES")
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(history) { item in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(item.date).font(.system(size: 10, design: .monospaced))
                                .foregroundColor(FSColor.cyan)
                            Text("M\(item.moodScore) · \(item.marketPosture)")
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundColor(FSColor.textSecondary)
                            Text(item.topPriority.prefix(40) + (item.topPriority.count > 40 ? "…" : ""))
                                .font(FSFont.body(11))
                                .foregroundColor(FSColor.textPrimary)
                                .frame(width: 160, alignment: .leading)
                        }
                        .padding(8)
                        .background(FSColor.cardBg)
                        .cornerRadius(6)
                    }
                }
            }
        }
    }

    private func sectionHeader(_ s: String) -> some View {
        Text(s)
            .font(.system(size: 12, weight: .bold, design: .monospaced))
            .foregroundColor(FSColor.cyan)
            .kerning(1.2)
    }

    private func question(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundColor(FSColor.textSecondary)
                .kerning(1.0)
            content()
        }
        .padding(.top, 4)
    }

    private func row(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundColor(FSColor.textSecondary).kerning(0.8)
            Text(value).font(FSFont.body(14)).foregroundColor(FSColor.textPrimary).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func preloadFormFromQuiz(_ q: MorningQuiz) {
        moodScore = Double(q.moodScore)
        moodWord = q.moodWord
        topPriority = q.topPriority
        let t = q.supportingTasks
        task1 = t.indices.contains(0) ? t[0] : ""
        task2 = t.indices.contains(1) ? t[1] : ""
        task3 = t.indices.contains(2) ? t[2] : ""
        marketPosture = q.marketPosture
        researchQuestion = q.researchQuestion
        gratitude = q.gratitude
        yesterdayLesson = q.yesterdayLesson
        notes = q.notes
    }

    private func load() async {
        loading = true; defer { loading = false }
        error = nil
        do {
            async let qT = try? await client.fetchMorningQuizToday()
            async let wT = try? await client.fetchWisdomToday()
            async let hT = try? await client.fetchMorningQuizHistory(limit: 14)
            todaysQuiz = await qT ?? nil
            wisdom = await wT ?? nil
            history = await hT ?? []
        }
    }

    private func submit() async {
        submitting = true; defer { submitting = false }
        submitMsg = nil
        do {
            let tasks = [task1, task2, task3].filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            let resp = try await client.submitMorningQuiz(
                moodScore: Int(moodScore),
                moodWord: moodWord,
                topPriority: topPriority,
                supportingTasks: tasks,
                marketPosture: marketPosture,
                researchQuestion: researchQuestion,
                gratitude: gratitude,
                yesterdayLesson: yesterdayLesson,
                notes: notes,
                wisdomIDShown: wisdom?.id ?? ""
            )
            let fired = resp["fired"] as? [String: Any] ?? [:]
            submitMsg = "Submitted. Fired: " + fired.compactMap { k, v in (v as? Bool == true) ? k : nil }.joined(separator: ", ")
            await load()
        } catch {
            submitMsg = "ERROR — \(error.localizedDescription)"
        }
    }
}
