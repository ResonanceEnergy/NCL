import SwiftUI

#if canImport(UIKit)
import UIKit
public typealias PlatformImage = UIImage
#elseif canImport(AppKit)
import AppKit
public typealias PlatformImage = NSImage
#endif

// MARK: - Wave 14G Phase 4 — cross-platform shims
//
// Centralises the pasteboard / keyboard / window APIs that differ between
// iOS and macOS so view files can stay platform-agnostic.

public enum Platform {
    /// Write a string to the system pasteboard. iOS: UIPasteboard.general.
    /// macOS: NSPasteboard.general.
    public static func setPasteboard(_ s: String) {
        #if canImport(UIKit)
        UIPasteboard.general.string = s
        #elseif canImport(AppKit)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(s, forType: .string)
        #endif
    }

    /// Dismiss the on-screen keyboard. iOS: resignFirstResponder via
    /// UIApplication. macOS: no-op (no software keyboard).
    public static func dismissKeyboard() {
        #if canImport(UIKit)
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil, from: nil, for: nil
        )
        #endif
    }

    /// Best-effort: return the largest connected window size for placement
    /// math. iOS: largest UIWindowScene. macOS: main screen frame.
    public static var primaryWindowSize: CGSize {
        #if canImport(UIKit)
        if let scene = UIApplication.shared.connectedScenes
            .compactMap({ $0 as? UIWindowScene })
            .first(where: { $0.activationState == .foregroundActive }) {
            return scene.coordinateSpace.bounds.size
        }
        return CGSize(width: 0, height: 0)
        #elseif canImport(AppKit)
        return NSScreen.main?.frame.size ?? .zero
        #endif
    }

    /// Load a PlatformImage from data. iOS: UIImage(data:). macOS:
    /// NSImage(data:).
    public static func image(from data: Data) -> PlatformImage? {
        #if canImport(UIKit)
        return UIImage(data: data)
        #elseif canImport(AppKit)
        return NSImage(data: data)
        #endif
    }
}

// MARK: - Image SwiftUI helper
//
// SwiftUI's `Image(uiImage:)` doesn't exist on macOS, and
// `Image(nsImage:)` doesn't exist on iOS. This wraps both so view code
// can write `PlatformImageView(platformImage:)`.

public struct PlatformImageView: View {
    let platformImage: PlatformImage

    public init(platformImage: PlatformImage) {
        self.platformImage = platformImage
    }

    public var body: some View {
        #if canImport(UIKit)
        Image(uiImage: platformImage).resizable()
        #elseif canImport(AppKit)
        Image(nsImage: platformImage).resizable()
        #endif
    }
}
