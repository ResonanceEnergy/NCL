// BackgroundScheduler.swift — NCL iOS Companion
// Micro-batching: schedules heavy tasks (consolidation, pattern analysis, learning)
// to run only when device is charging and/or idle.

import Foundation

// MARK: - ScheduledTask

struct ScheduledTask: Identifiable {
    let id: String
    let name: String
    let interval: TimeInterval        // minimum seconds between runs
    let requiresCharging: Bool
    let requiresIdle: Bool
    let action: () -> Void
    var lastRun: Date?
}

// MARK: - DeviceState (abstraction for testability)

protocol DeviceStateProvider {
    var isCharging: Bool { get }
    var isIdle: Bool { get }             // e.g. screen off for >5 min
    var batteryLevel: Float { get }      // 0.0–1.0
}

struct DefaultDeviceState: DeviceStateProvider {
    var isCharging: Bool {
        #if canImport(UIKit)
        UIDevice.current.isBatteryMonitoringEnabled = true
        let state = UIDevice.current.batteryState
        return state == .charging || state == .full
        #else
        // macOS / simulator fallback — assume plugged in
        return true
        #endif
    }

    var isIdle: Bool {
        #if canImport(UIKit)
        // Treat the device as idle if no touch for ≥ 5 minutes.
        // UIApplication.shared is unavailable in extensions, so guard.
        if let app = (NSClassFromString("UIApplication") as? NSObject.Type),
           let shared = app.value(forKey: "sharedApplication") as? NSObject,
           let idleTimer = shared.value(forKey: "idleTimerDisabled") as? Bool {
            // If idle timer is not disabled, we treat the device as idle
            // when battery state is not .unplugged and battery > 50%
            return !idleTimer
        }
        return true
        #else
        return true
        #endif
    }

    var batteryLevel: Float {
        #if canImport(UIKit)
        UIDevice.current.isBatteryMonitoringEnabled = true
        let level = UIDevice.current.batteryLevel
        // batteryLevel returns -1.0 when monitoring is unsupported (simulator)
        return level >= 0 ? level : 1.0
        #else
        return 1.0
        #endif
    }
}

// MARK: - BackgroundScheduler

final class BackgroundScheduler {

    private var tasks: [String: ScheduledTask] = [:]
    private var timer: Timer?
    private let checkInterval: TimeInterval
    private let deviceState: DeviceStateProvider
    private let queue = DispatchQueue(label: "ncl.scheduler", qos: .background)

    init(checkInterval: TimeInterval = 300, // 5 minutes
         deviceState: DeviceStateProvider = DefaultDeviceState()) {
        self.checkInterval = checkInterval
        self.deviceState = deviceState
    }

    // MARK: - Public API

    /// Register a recurring background task.
    func register(task: ScheduledTask) {
        tasks[task.id] = task
    }

    /// Start the scheduler loop.
    func start() {
        stop()
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.timer = Timer.scheduledTimer(withTimeInterval: self.checkInterval, repeats: true) { [weak self] _ in
                self?.tick()
            }
        }
    }

    /// Stop the scheduler.
    func stop() {
        timer?.invalidate()
        timer = nil
    }

    /// Force-run eligible tasks now (for testing / manual trigger).
    func runEligibleNow() {
        tick()
    }

    /// Get task status for dashboard.
    func taskStatuses() -> [(id: String, name: String, lastRun: Date?, nextEligible: Date?)] {
        tasks.values.map { task in
            let nextEligible: Date?
            if let lastRun = task.lastRun {
                nextEligible = lastRun.addingTimeInterval(task.interval)
            } else {
                nextEligible = Date() // eligible now
            }
            return (task.id, task.name, task.lastRun, nextEligible)
        }
    }

    // MARK: - Private

    private func tick() {
        queue.async { [weak self] in
            guard let self = self else { return }
            let now = Date()

            for (id, task) in self.tasks {
                // Check timing
                if let lastRun = task.lastRun,
                   now.timeIntervalSince(lastRun) < task.interval {
                    continue
                }

                // Check device conditions
                if task.requiresCharging && !self.deviceState.isCharging { continue }
                if task.requiresIdle && !self.deviceState.isIdle { continue }

                // Battery floor: don't run heavy tasks below 20% unless charging
                if !self.deviceState.isCharging && self.deviceState.batteryLevel < 0.2 { continue }

                // Execute
                task.action()
                self.tasks[id]?.lastRun = now
            }
        }
    }
}
