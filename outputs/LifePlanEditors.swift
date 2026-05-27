import SwiftUI

// MARK: - Wave 14F — Life Plan editor sheets
//
// Editor screens for Vision, Goal, Plan + review wizards + vision board.
// Surfaces presented as .sheet from LifePlanView and JournalView.

// ── Vision Editor ────────────────────────────────────────────────────────

struct VisionEditorSheet: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    @Environment(\.dismiss) var dismiss
    let existing: Vision?
    var onSaved: (() -> Void)? = nil

    @State private var title: String = ""
    @State private var narrative: String = ""
    @State private var horizonYears: Int = 10
    @State private var pillarsText: String = ""
    @State private var submitting = false
    @State private var err: String? = nil

    var body: some View {
        NavigationView {
            Form {
                Section("Title") {
                    TextField("Free, healthy, building", text: $title)
                }
                Section("Horizon (years)") {
                    Stepper("\(horizonYears) years", value: $horizonYears, in: 1...50)
                }
                Section("Pillars (comma-separated)") {
                    TextField("Financial independence, Health span, Creative output", text: $pillarsText)
                }
                Section("Narrative") {
                    TextEditor(text: $narrative).frame(minHeight: 180)
                }
                if let e = err {
                    Text(e).foregroundColor(.red).font(.caption)
                }
                Section {
                    Button(submitting ? "Saving…" : "Save Vision") { Task { await save() } }
                        .disabled(submitting || title.isEmpty)
                }
            }
            .navigationTitle(existing == nil ? "New Vision" : "Edit Vision")
            .toolbar { ToolbarItem(placement: .navigationBarLeading) { Button("Cancel") { dismiss() } } }
            .onAppear { preload() }
        }
    }

    private func preload() {
        guard let v = existing else { return }
        title = v.title; narrative = v.narrative; horizonYears = v.horizonYears
        pillarsText = v.pillars.joined(separator: ", ")
    }

    private func save() async {
        submitting = true; defer { submitting = false }
        let pillars = pillarsText.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        do {
            _ = try await brainClient.setVision(title: title, narrative: narrative, horizonYears: horizonYears, pillars: pillars)
            onSaved?(); dismiss()
        } catch { err = error.localizedDescription }
    }
}

// ── Goal Editor ──────────────────────────────────────────────────────────

struct GoalEditorSheet: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    @Environment(\.dismiss) var dismiss
    var onSaved: (() -> Void)? = nil

    @State private var scope: String = "quarter"
    @State private var objective: String = ""
    @State private var confidence: Double = 7
    @State private var status: String = "active"
    @State private var krRows: [KREntry] = [KREntry()]
    @State private var startsAt: Date = .init()
    @State private var endsAt: Date = .init().addingTimeInterval(60*60*24*90)
    @State private var submitting = false
    @State private var err: String? = nil

    private let scopes = ["year", "quarter", "month", "week"]
    private let dfmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f }()

    var body: some View {
        NavigationView {
            Form {
                Section("Scope") {
                    Picker("scope", selection: $scope) {
                        ForEach(scopes, id: \.self) { Text($0.capitalized).tag($0) }
                    }.pickerStyle(.segmented)
                }
                Section("Objective (1 sentence, ambitious)") {
                    TextField("Hit $X NAV with health intact", text: $objective, axis: .vertical).lineLimit(2...4)
                }
                Section("Key Results") {
                    ForEach($krRows) { $row in
                        VStack(alignment: .leading) {
                            TextField("Description", text: $row.description)
                            HStack {
                                TextField("Target", value: $row.target, format: .number).keyboardType(.decimalPad).frame(width: 80)
                                TextField("Current", value: $row.current, format: .number).keyboardType(.decimalPad).frame(width: 80)
                                TextField("Unit ($, %, etc)", text: $row.unit).frame(width: 100)
                            }
                        }
                    }
                    Button("+ Add KR") { krRows.append(KREntry()) }
                }
                Section("Dates + Confidence") {
                    DatePicker("Starts", selection: $startsAt, displayedComponents: .date)
                    DatePicker("Ends", selection: $endsAt, displayedComponents: .date)
                    HStack { Text("Confidence"); Slider(value: $confidence, in: 1...10, step: 1); Text("\(Int(confidence))") }
                }
                if let e = err { Text(e).foregroundColor(.red).font(.caption) }
                Section {
                    Button(submitting ? "Saving…" : "Save Goal") { Task { await save() } }
                        .disabled(submitting || objective.isEmpty)
                }
            }
            .navigationTitle("New Goal")
            .toolbar { ToolbarItem(placement: .navigationBarLeading) { Button("Cancel") { dismiss() } } }
        }
    }

    private func save() async {
        submitting = true; defer { submitting = false }
        let krs = krRows.filter { !$0.description.isEmpty }.map { row in
            ["description": row.description, "target": row.target, "current": row.current, "unit": row.unit] as [String: Any]
        }
        let body: [String: Any] = [
            "scope": scope, "objective": objective, "key_results": krs,
            "starts_at": dfmt.string(from: startsAt), "ends_at": dfmt.string(from: endsAt),
            "status": status, "confidence": Int(confidence),
        ]
        do {
            _ = try await brainClient.executeCommand(endpoint: "/life/goal", method: "POST", body: body)
            onSaved?(); dismiss()
        } catch { err = error.localizedDescription }
    }
}

struct KREntry: Identifiable {
    let id = UUID()
    var description: String = ""
    var target: Double = 1.0
    var current: Double = 0.0
    var unit: String = "count"
}

// ── Plan Editor ──────────────────────────────────────────────────────────

struct PlanEditorSheet: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    @Environment(\.dismiss) var dismiss
    var onSaved: (() -> Void)? = nil

    @State private var title: String = ""
    @State private var kind: String = "project"
    @State private var hasTarget: Bool = false
    @State private var targetDate: Date = .init()
    @State private var hasBudget: Bool = false
    @State private var budget: Double = 0
    @State private var narrative: String = ""
    @State private var checklistText: String = ""
    @State private var submitting = false
    @State private var err: String? = nil

    private let kinds = ["project", "vacation", "retirement", "purchase", "life-event"]
    private let dfmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f }()

    var body: some View {
        NavigationView {
            Form {
                Section("Title") { TextField("Paraguay trip Aug 2026", text: $title) }
                Section("Kind") {
                    Picker("kind", selection: $kind) {
                        ForEach(kinds, id: \.self) { Text($0.capitalized).tag($0) }
                    }.pickerStyle(.menu)
                }
                Section("Target date") {
                    Toggle("Has a target date", isOn: $hasTarget)
                    if hasTarget { DatePicker("Target", selection: $targetDate, displayedComponents: .date) }
                }
                Section("Budget") {
                    Toggle("Has a budget", isOn: $hasBudget)
                    if hasBudget {
                        TextField("USD", value: $budget, format: .number).keyboardType(.decimalPad)
                    }
                }
                Section("Narrative (vision-first description)") {
                    TextEditor(text: $narrative).frame(minHeight: 120)
                }
                Section("Checklist (one per line)") {
                    TextEditor(text: $checklistText).frame(minHeight: 100)
                }
                if let e = err { Text(e).foregroundColor(.red).font(.caption) }
                Section {
                    Button(submitting ? "Saving…" : "Save Plan") { Task { await save() } }
                        .disabled(submitting || title.isEmpty)
                }
            }
            .navigationTitle("New Plan")
            .toolbar { ToolbarItem(placement: .navigationBarLeading) { Button("Cancel") { dismiss() } } }
        }
    }

    private func save() async {
        submitting = true; defer { submitting = false }
        let items = checklistText.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        let checklist = items.map { ["text": $0] as [String: Any] }
        var body: [String: Any] = ["title": title, "kind": kind, "narrative": narrative, "status": "planning", "checklist": checklist]
        if hasTarget { body["target_date"] = dfmt.string(from: targetDate) }
        if hasBudget { body["budget_usd"] = budget }
        do {
            _ = try await brainClient.executeCommand(endpoint: "/life/plan", method: "POST", body: body)
            onSaved?(); dismiss()
        } catch { err = error.localizedDescription }
    }
}

// ── Weekly Review Wizard ─────────────────────────────────────────────────

struct WeeklyReviewSheet: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    @Environment(\.dismiss) var dismiss
    @State private var wins: [String] = ["", "", ""]
    @State private var biggestMiss: String = ""
    @State private var missLesson: String = ""
    @State private var energy: Double = 7
    @State private var focus: Double = 7
    @State private var mood: Double = 7
    @State private var needleMoved: String = ""
    @State private var topKR: String = ""
    @State private var nextWeekFocus: String = ""
    @State private var threadsText: String = ""
    @State private var notes: String = ""
    @State private var submitting = false
    @State private var err: String? = nil

    var body: some View {
        NavigationView {
            Form {
                Section("Top 3 wins this week") {
                    ForEach(0..<wins.count, id: \.self) { i in
                        TextField("Win \(i+1)", text: $wins[i])
                    }
                }
                Section("Biggest miss + lesson") {
                    TextField("What missed", text: $biggestMiss)
                    TextField("Lesson learned", text: $missLesson)
                }
                Section("Self-scores (1-10)") {
                    HStack { Text("Energy"); Slider(value: $energy, in: 1...10, step: 1); Text("\(Int(energy))") }
                    HStack { Text("Focus"); Slider(value: $focus, in: 1...10, step: 1); Text("\(Int(focus))") }
                    HStack { Text("Mood"); Slider(value: $mood, in: 1...10, step: 1); Text("\(Int(mood))") }
                }
                Section("Goal progress") {
                    TextField("Did I move the needle? Which KR?", text: $needleMoved, axis: .vertical).lineLimit(2...4)
                    TextField("Top KR that moved most", text: $topKR)
                }
                Section("Next week") {
                    TextField("SINGLE focus for next week", text: $nextWeekFocus, axis: .vertical).lineLimit(1...3)
                    TextField("Open threads (one per line)", text: $threadsText, axis: .vertical).lineLimit(2...5)
                }
                Section("Notes") { TextEditor(text: $notes).frame(minHeight: 80) }
                if let e = err { Text(e).foregroundColor(.red).font(.caption) }
                Section {
                    Button(submitting ? "Saving…" : "Submit Weekly Review") { Task { await save() } }
                        .disabled(submitting || nextWeekFocus.isEmpty)
                }
            }
            .navigationTitle("Weekly Review")
            .toolbar { ToolbarItem(placement: .navigationBarLeading) { Button("Cancel") { dismiss() } } }
        }
    }

    private func save() async {
        submitting = true; defer { submitting = false }
        let threads = threadsText.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        let body: [String: Any] = [
            "wins": wins.filter { !$0.isEmpty }, "biggest_miss": biggestMiss, "miss_lesson": missLesson,
            "energy_score": Int(energy), "focus_score": Int(focus), "mood_score": Int(mood),
            "needle_moved": needleMoved, "top_kr_movement": topKR,
            "next_week_focus": nextWeekFocus, "open_threads": threads, "notes": notes,
        ]
        do {
            _ = try await brainClient.executeCommand(endpoint: "/journal/weekly-review", method: "POST", body: body)
            dismiss()
        } catch { err = error.localizedDescription }
    }
}

// ── Yearly Review Wizard ─────────────────────────────────────────────────

struct YearlyReviewSheet: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    @Environment(\.dismiss) var dismiss
    @State private var year: Int = Calendar.current.component(.year, from: .init())
    @State private var wins: [String] = ["", "", ""]
    @State private var hardLesson: String = ""
    @State private var wouldChange: String = ""
    @State private var northStarProgress: String = ""
    @State private var themesText: String = ""
    @State private var openQuestion: String = ""
    @State private var notes: String = ""
    @State private var submitting = false
    @State private var err: String? = nil

    var body: some View {
        NavigationView {
            Form {
                Section("Year") {
                    Stepper("\(year)", value: $year, in: 2020...2100)
                }
                Section("3 wins of the year") {
                    ForEach(0..<wins.count, id: \.self) { i in
                        TextField("Win \(i+1)", text: $wins[i], axis: .vertical).lineLimit(1...3)
                    }
                    Button("+ Add another win") { wins.append("") }
                }
                Section("Hard lesson") { TextEditor(text: $hardLesson).frame(minHeight: 80) }
                Section("Would change") { TextEditor(text: $wouldChange).frame(minHeight: 80) }
                Section("North star progress (vs vision)") { TextEditor(text: $northStarProgress).frame(minHeight: 80) }
                Section("Next year themes (one per line)") { TextEditor(text: $themesText).frame(minHeight: 80) }
                Section("Open question to carry into the new year") {
                    TextField("Question", text: $openQuestion, axis: .vertical).lineLimit(2...4)
                }
                Section("Notes") { TextEditor(text: $notes).frame(minHeight: 80) }
                if let e = err { Text(e).foregroundColor(.red).font(.caption) }
                Section {
                    Button(submitting ? "Saving…" : "Submit Yearly Review") { Task { await save() } }
                        .disabled(submitting)
                }
            }
            .navigationTitle("Yearly Review \(year)")
            .toolbar { ToolbarItem(placement: .navigationBarLeading) { Button("Cancel") { dismiss() } } }
        }
    }

    private func save() async {
        submitting = true; defer { submitting = false }
        let themes = themesText.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        let body: [String: Any] = [
            "year": year, "wins": wins.filter { !$0.isEmpty },
            "hard_lesson": hardLesson, "would_change": wouldChange,
            "north_star_progress": northStarProgress, "next_year_themes": themes,
            "open_question": openQuestion, "notes": notes,
        ]
        do {
            _ = try await brainClient.executeCommand(endpoint: "/journal/yearly-review", method: "POST", body: body)
            dismiss()
        } catch { err = error.localizedDescription }
    }
}

// ── Vision Board Viewer (with Generate button) ───────────────────────────

struct VisionBoardSheet: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    @Environment(\.dismiss) var dismiss

    @State private var image: UIImage? = nil
    @State private var filename: String = ""
    @State private var status: String = ""
    @State private var generating = false
    @State private var loading = false
    @State private var err: String? = nil

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 16) {
                    if let img = image {
                        Image(uiImage: img)
                            .resizable().aspectRatio(contentMode: .fit)
                            .cornerRadius(8)
                            .frame(maxWidth: .infinity)
                        if !filename.isEmpty {
                            Text(filename).font(.system(size: 11, design: .monospaced)).foregroundColor(.secondary)
                        }
                    } else if loading {
                        ProgressView("Loading latest board…").padding()
                    } else {
                        VStack(spacing: 10) {
                            Image(systemName: "photo.on.rectangle.angled").font(.system(size: 60)).foregroundColor(.secondary)
                            Text("No board generated yet").foregroundColor(.secondary)
                            Text("Generating costs ~$0.04 and takes 10–30s").font(.caption).foregroundColor(.secondary)
                        }.padding()
                    }

                    Button {
                        Task { await generate() }
                    } label: {
                        HStack {
                            if generating { ProgressView().tint(.white) }
                            Text(generating ? "Generating…" : "Generate New Board")
                                .font(.system(size: 14, weight: .bold, design: .monospaced))
                                .foregroundColor(.white)
                        }
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        .background(generating ? Color.gray : FSColor.orange)
                        .cornerRadius(8)
                    }
                    .disabled(generating)

                    if let e = err { Text(e).foregroundColor(.red).font(.caption) }
                    if !status.isEmpty { Text(status).font(.caption).foregroundColor(.green) }
                }
                .padding()
            }
            .navigationTitle("Vision Board")
            .toolbar { ToolbarItem(placement: .navigationBarTrailing) { Button("Done") { dismiss() } } }
            .task { await loadLatest() }
        }
    }

    private func loadLatest() async {
        loading = true; defer { loading = false }
        do {
            let r = try await brainClient.executeCommand(endpoint: "/life/vision/board/latest", method: "GET")
            if let b64 = r["image_b64"] as? String, let data = Data(base64Encoded: b64) {
                image = UIImage(data: data)
                filename = r["filename"] as? String ?? ""
            }
        } catch { err = error.localizedDescription }
    }

    private func generate() async {
        generating = true; defer { generating = false }
        err = nil; status = ""
        do {
            let r = try await brainClient.executeCommand(endpoint: "/life/vision/board/generate", method: "POST")
            let s = r["status"] as? String ?? "?"
            if s == "ok" {
                status = "Generated · \(r["filename"] as? String ?? "")"
                await loadLatest()
            } else {
                err = "Status \(s): \(r["error"] as? String ?? "unknown")"
            }
        } catch { err = error.localizedDescription }
    }
}
