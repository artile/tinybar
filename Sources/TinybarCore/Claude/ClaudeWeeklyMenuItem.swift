import Foundation

/// A weekly account-wide reading. Missing or stale readings must not look like fresh numbers.
public struct ClaudeWeeklyMenuItem: Equatable, Sendable, Identifiable {
    public var id: String
    public var label: String
    public var percent: Int?
    public var stale: Bool

    public init(account: ClaudeProxyAccount) {
        id = account.id
        label = account.label
        stale = account.error != nil
        let weekly = account.snapshot?.windows.first {
            $0.kind == .weekly && !$0.isModelSpecific
        }
        percent = stale ? nil : weekly.map { Int($0.remainingPercent.rounded()) }
    }
}
