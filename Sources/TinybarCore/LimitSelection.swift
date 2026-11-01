import Foundation

/// One selectable limit. Account identity is independent of provider and display name.
public struct LimitSelection: Sendable {
    public var provider: ProviderID
    public var accountID: String?
    public var accountName: String?
    public var window: LimitWindow
    public var fetchedAt: Date
    public var stale: Bool

    public init(provider: ProviderID, accountID: String? = nil, accountName: String? = nil,
                window: LimitWindow, fetchedAt: Date, stale: Bool) {
        self.provider = provider
        self.accountID = accountID
        self.accountName = accountName
        self.window = window
        self.fetchedAt = fetchedAt
        self.stale = stale
    }

    public static func key(provider: ProviderID, accountID: String? = nil, windowID: String) -> String {
        "\(provider.rawValue)\(accountID.map { "@\($0)" } ?? "")/\(windowID)"
    }

    public var key: String { Self.key(provider: provider, accountID: accountID, windowID: window.id) }

    public static func choose(_ candidates: [Self], pinnedKey: String?) -> Self? {
        if let pinnedKey, let explicit = candidates.first(where: { $0.key == pinnedKey }) { return explicit }
        let general = candidates.filter { !$0.window.isModelSpecific }
        let fresh = general.filter { !$0.stale }
        let available = fresh.isEmpty ? general : fresh
        let runningOut = available.compactMap { candidate -> (Self, Date)? in
            guard !candidate.stale, let at = candidate.window.runOutTime(asOf: candidate.fetchedAt),
                  candidate.window.runsOutBeforeReset(at) else { return nil }
            return (candidate, at)
        }
        if let first = runningOut.min(by: { $0.1 < $1.1 }) { return first.0 }
        return available.min {
            ($0.window.remainingPercent, $0.window.resetsAt ?? .distantFuture, $0.key)
                < ($1.window.remainingPercent, $1.window.resetsAt ?? .distantFuture, $1.key)
        }
    }
}
