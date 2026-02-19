import Foundation

public final class LocalKillSwitchService: KillSwitchServiceProtocol {
    private let key = "com.resonance.ncl.killswitch.engaged"
    private let store: UserDefaults

    public init(suiteName: String? = nil) {
        if let name = suiteName, let ud = UserDefaults(suiteName: name) {
            self.store = ud
        } else {
            self.store = UserDefaults.standard
        }
    }

    public func isEngaged() -> Bool {
        return store.bool(forKey: key)
    }

    // Engage the hard-stop
    public func engage() {
        store.set(true, forKey: key)
        store.synchronize()
    }

    // Re-enable MUST be guarded by AZ PRIME in calling code. Provide an explicit method but
    // it's the caller's responsibility to require interactive auth.
    public func clear() {
        store.set(false, forKey: key)
        store.synchronize()
    }
}
