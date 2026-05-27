#!/usr/bin/env python3
"""Wire promptHistory + relayClient + archiver into Mac app + MainWindow."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
s = open(p).read()
old = """    @StateObject private var ops = OpsClient()
    @StateObject private var brainClient = NCLBrainClient()
    @StateObject private var appSettings = AppSettings()
    @StateObject private var updater = UpdaterHolder()"""
new = """    @StateObject private var ops = OpsClient()
    @StateObject private var brainClient = NCLBrainClient()
    @StateObject private var appSettings = AppSettings()
    @StateObject private var promptHistory = PromptHistory()
    @StateObject private var relayClient = RelayClient()
    @StateObject private var archiver = ConversationArchiver()
    @StateObject private var updater = UpdaterHolder()"""
if "promptHistory" not in s:
    s = s.replace(old, new, 1)
    print("added promptHistory + relayClient + archiver")

# Inject into the main Window scene's environment
old_inject = """            NCLMainWindow()
                .environmentObject(brainClient)
                .environmentObject(appSettings)"""
new_inject = """            NCLMainWindow()
                .environmentObject(brainClient)
                .environmentObject(appSettings)
                .environmentObject(promptHistory)
                .environmentObject(relayClient)
                .environmentObject(archiver)"""
if "environmentObject(promptHistory)" not in s:
    s = s.replace(old_inject, new_inject, 1)
    print("injected envobjects into main window")

open(p, "w").write(s)
