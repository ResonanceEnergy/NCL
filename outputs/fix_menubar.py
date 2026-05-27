#!/usr/bin/env python3
p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
s = open(p).read()
old = (
    '        .keyboardShortcut("2", modifiers: .command)\n'
    "        .defaultSize(width: 900, height: 760)\n"
    "\n"
    "    }\n"
    "}\n"
)
new = (
    '        .keyboardShortcut("2", modifiers: .command)\n'
    "        .defaultSize(width: 900, height: 760)\n"
    "\n"
    "        // Wave 14G P9 — Cmd+3..6 Window scenes\n"
    '        Window("Night Watch", id: "nightwatch") {\n'
    "            NavigationStack { NightWatchContainer() }\n"
    "                .environmentObject(brainClient)\n"
    "                .environmentObject(appSettings)\n"
    "        }\n"
    '        .keyboardShortcut("3", modifiers: .command)\n'
    "        .defaultSize(width: 900, height: 760)\n"
    "\n"
    '        Window("Memory", id: "memory") {\n'
    "            NavigationStack { MemoryView() }\n"
    "                .environmentObject(brainClient)\n"
    "                .environmentObject(appSettings)\n"
    "        }\n"
    '        .keyboardShortcut("4", modifiers: .command)\n'
    "        .defaultSize(width: 1000, height: 800)\n"
    "\n"
    '        Window("Calendar", id: "calendar") {\n'
    "            NavigationStack { CalendarView() }\n"
    "                .environmentObject(brainClient)\n"
    "                .environmentObject(appSettings)\n"
    "        }\n"
    '        .keyboardShortcut("5", modifiers: .command)\n'
    "        .defaultSize(width: 1000, height: 760)\n"
    "\n"
    '        Window("Intel", id: "intel") {\n'
    "            NavigationStack { IntelView() }\n"
    "                .environmentObject(brainClient)\n"
    "                .environmentObject(appSettings)\n"
    "        }\n"
    '        .keyboardShortcut("6", modifiers: .command)\n'
    "        .defaultSize(width: 1100, height: 800)\n"
    "        .commands {\n"
    "            CommandGroup(after: .appInfo) {\n"
    "                CheckForUpdatesView(holder: updater)\n"
    "            }\n"
    "        }\n"
    "    }\n"
    "}\n"
)
if 'Window("Night Watch"' in s:
    print("already")
elif old in s:
    open(p, "w").write(s.replace(old, new, 1))
    print("PATCHED")
else:
    print("OLD NOT FOUND")
    print(repr(s[s.find('keyboardShortcut("2"') : s.find('keyboardShortcut("2"') + 200]))
