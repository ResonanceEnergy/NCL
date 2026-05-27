#!/usr/bin/env python3
"""Wave 14G Phase 4 — pull Sources/ subset into NCLDesktop target."""

p = "/Users/natrix/Projects/FirstStrike/project.yml"
src = open(p).read()

old = """  NCLDesktop:
    type: application
    platform: macOS
    deploymentTarget: "14.0"
    sources:
      - path: MacSources
        type: group
    settings:"""

new = """  NCLDesktop:
    type: application
    platform: macOS
    deploymentTarget: "14.0"
    sources:
      - path: MacSources
        type: group
      - path: Sources/Models
        type: group
      - path: Sources/Network
        type: group
      - path: Sources/Services
        type: group
      - path: Sources/App/Theme.swift
      - path: Sources/App/PlatformShim.swift
      - path: Sources/Views/Journal/LifePlanView.swift
      - path: Sources/Views/Journal/LifePlanEditors.swift
      - path: Sources/Views/Journal/MorningQuizView.swift
      - path: Sources/Views/Intel/NightWatchView.swift
      - path: Sources/Views/Intel/IntelSignalCard.swift
      - path: Sources/Views/BriefRenderer.swift
    settings:"""

if "Sources/Models" not in src:
    src = src.replace(old, new, 1)
    open(p, "w").write(src)
    print("patched project.yml")
else:
    print("already patched")
