import Foundation

// MARK: - Wave 14I item 10 — NCLBrainClient rotation fetcher
//
// GET /intelligence/rotation returns today's capital rotation snapshot
// (sectors, breadth, quadrants, style ratios, cycle phase).

extension NCLBrainClient {
    func fetchRotation() async throws -> RotationEnvelope {
        guard let url = URL(string: "\(baseURL)/intelligence/rotation") else {
            throw BrainError.invalidURL
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 15
        if !authToken.isEmpty {
            req.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        }
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else {
            throw BrainError.httpError(code: -1, message: "no http response")
        }
        guard http.statusCode == 200 else {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw BrainError.httpError(code: http.statusCode, message: body)
        }
        return try JSONDecoder().decode(RotationEnvelope.self, from: data)
    }

    func fireRotationBuild() async throws -> RotationEnvelope {
        guard let url = URL(string: "\(baseURL)/intelligence/rotation/fire") else {
            throw BrainError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 90
        if !authToken.isEmpty {
            req.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        }
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
            let body = (resp as? HTTPURLResponse).map { "\($0.statusCode)" } ?? "-1"
            throw BrainError.httpError(code: Int(body) ?? -1, message: body)
        }
        struct FireResponse: Decodable {
            let rotation: RotationSnapshot?
            let styleRatios: StyleSnapshot?
            let cyclePhase: CycleSnapshot?
            enum CodingKeys: String, CodingKey {
                case rotation
                case styleRatios = "style_ratios"
                case cyclePhase = "cycle_phase"
            }
        }
        let r = try JSONDecoder().decode(FireResponse.self, from: data)
        return RotationEnvelope(
            date: r.rotation?.date,
            rotation: r.rotation,
            styleRatios: r.styleRatios,
            cyclePhase: r.cyclePhase
        )
    }
}
