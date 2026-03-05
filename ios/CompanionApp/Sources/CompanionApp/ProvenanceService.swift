// ProvenanceService.swift — NCL iOS Companion
// Builds and validates provenance graphs linking events → missions → insights → actions.

import Foundation

// MARK: - Provenance Node

struct ProvenanceNode: Codable, Identifiable {
    enum NodeType: String, Codable {
        case event, mission, insight, action, derivedData
    }

    let id: String
    let nodeType: NodeType
    let label: String
    let timestamp: Date
    let parentIDs: [String]     // upstream nodes this was derived from
    let metadata: [String: String]
}

// MARK: - ProvenanceGraph

struct ProvenanceGraph: Codable {
    let rootID: String
    var nodes: [String: ProvenanceNode] = [:]

    /// All nodes reachable from a given node (full ancestor chain).
    func ancestors(of nodeID: String) -> [ProvenanceNode] {
        var visited = Set<String>()
        var result: [ProvenanceNode] = []
        var queue = [nodeID]

        while !queue.isEmpty {
            let current = queue.removeFirst()
            guard !visited.contains(current), let node = nodes[current] else { continue }
            visited.insert(current)
            result.append(node)
            queue.append(contentsOf: node.parentIDs)
        }

        return result
    }

    /// Validate that a node has a complete provenance chain back to source events.
    func hasCompleteChain(nodeID: String) -> Bool {
        let chain = ancestors(of: nodeID)
        return chain.contains { $0.nodeType == .event }
    }
}

// MARK: - ProvenanceService

final class ProvenanceService {

    private let fileURL: URL
    private let queue = DispatchQueue(label: "ncl.provenance", qos: .utility)
    private(set) var graph: ProvenanceGraph

    init(directory: URL? = nil) {
        let dir = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("NCL", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        self.fileURL = dir.appendingPathComponent("provenance_graph.json")

        if let data = try? Data(contentsOf: fileURL),
           let loaded = try? JSONDecoder().decode(ProvenanceGraph.self, from: data) {
            self.graph = loaded
        } else {
            self.graph = ProvenanceGraph(rootID: "ncl-root")
        }
    }

    // MARK: - Public API

    /// Record a new provenance node.
    func addNode(_ node: ProvenanceNode) {
        queue.sync {
            graph.nodes[node.id] = node
            persist()
        }
    }

    /// Record an event as a source node (no parents).
    func recordEvent(eventID: String, eventType: String, occurredAt: Date) -> ProvenanceNode {
        let node = ProvenanceNode(
            id: eventID, nodeType: .event, label: eventType,
            timestamp: occurredAt, parentIDs: [], metadata: [:]
        )
        addNode(node)
        return node
    }

    /// Record a mission derived from events.
    func recordMission(missionID: String, label: String, sourceEventIDs: [String]) -> ProvenanceNode {
        let node = ProvenanceNode(
            id: missionID, nodeType: .mission, label: label,
            timestamp: Date(), parentIDs: sourceEventIDs, metadata: [:]
        )
        addNode(node)
        return node
    }

    /// Record an insight derived from missions or events.
    func recordInsight(insightID: String, label: String, sourceIDs: [String]) -> ProvenanceNode {
        let node = ProvenanceNode(
            id: insightID, nodeType: .insight, label: label,
            timestamp: Date(), parentIDs: sourceIDs, metadata: [:]
        )
        addNode(node)
        return node
    }

    /// Record an action derived from insights or missions.
    func recordAction(actionID: String, label: String, sourceIDs: [String]) -> ProvenanceNode {
        let node = ProvenanceNode(
            id: actionID, nodeType: .action, label: label,
            timestamp: Date(), parentIDs: sourceIDs, metadata: [:]
        )
        addNode(node)
        return node
    }

    /// Validate that an action has complete provenance back to source events.
    func validateProvenance(actionID: String) -> Bool {
        queue.sync { graph.hasCompleteChain(nodeID: actionID) }
    }

    /// Get the full provenance chain for a node.
    func provenanceChain(for nodeID: String) -> [String] {
        queue.sync { graph.ancestors(of: nodeID).map { $0.id } }
    }

    /// Export graph as JSON.
    func exportJSON() -> Data? {
        queue.sync { try? JSONEncoder().encode(graph) }
    }

    // MARK: - Private

    private func persist() {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        if let data = try? encoder.encode(graph) {
            try? data.write(to: fileURL, options: .atomic)
        }
    }
}
