import Foundation

public final class DummyIncidentLedger: IncidentLedgerProtocol {
    public init() {}
    public func append(incident: [String : Any]) {
        // No-op for starter; production should implement append-only storage
        print("Incident emitted: \(incident)")
    }
}
