// swift-tools-version: 5.9
// Package.swift — NCL iOS CompanionApp
// Enables `swift build` and `swift test` from the ios/CompanionApp directory.

import PackageDescription

let package = Package(
    name: "CompanionApp",
    platforms: [
        .iOS(.v16),
        .macOS(.v13)
    ],
    products: [
        .library(name: "CompanionApp", targets: ["CompanionApp"]),
    ],
    targets: [
        .target(
            name: "CompanionApp",
            path: "Sources/CompanionApp"
        ),
        .testTarget(
            name: "CompanionAppTests",
            dependencies: ["CompanionApp"],
            path: "Tests/CompanionAppTests"
        ),
    ]
)
