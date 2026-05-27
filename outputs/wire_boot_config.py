#!/usr/bin/env python3
"""Add boot-time client config + health-check loop to NCLMainWindow."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MainWindow.swift"
s = open(p).read()

old = """        .onAppear {
            section = FSTab(rawValue: rawSection) ?? .dashboard
            MacAuthSeeder.seedIfEmpty(appSettings)
        }"""

new = """        .onAppear {
            section = FSTab(rawValue: rawSection) ?? .dashboard
        }
        .task {
            // Seed brain auth token from ~/dev/NCL/.env BEFORE configuring
            // the brain client, so the configure() call sees the real token.
            MacAuthSeeder.seedIfEmpty(appSettings)
            // Mirror iOS FirstStrikeApp boot: hand AppSettings values into
            // NCLBrainClient so all data fetches across the embedded iOS
            // views (Dashboard / Portfolio / Intel / Memory / Calendar /
            // Journal) actually hit the Brain with the right URL + token.
            brainClient.configure(
                ip: appSettings.brainHost,
                port: appSettings.brainPort,
                token: appSettings.brainAuthToken
            )
            // Initial health ping so the connection chip in Dashboard
            // flips to "Online" without waiting for user interaction.
            if appSettings.useBrainDirect {
                _ = await brainClient.checkHealth()
            } else {
                await relayClient.checkHealth(settings: appSettings)
            }
            // Continuous 15s heartbeat — same cadence as iOS.
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 15_000_000_000)
                guard !Task.isCancelled else { break }
                if appSettings.useBrainDirect {
                    _ = await brainClient.checkHealth()
                } else {
                    await relayClient.checkHealth(settings: appSettings)
                }
            }
        }"""

if ".task {" in s and "brainClient.configure" in s:
    print("already wired")
elif old in s:
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print("wired boot config + heartbeat")
else:
    print("OLD NOT FOUND")
