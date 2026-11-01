import Foundation
import Testing
@testable import TinybarCore

private func weeklyAccount(used: Double?, error: ProviderError? = nil, modelOnly: Bool = false) -> ClaudeProxyAccount {
    var windows = [LimitWindow(id: "session", title: "5-hour", usedPercent: 70, resetsAt: nil, durationSeconds: 18000)]
    if let used {
        windows.append(LimitWindow(id: modelOnly ? "opus-weekly" : "weekly", title: "Weekly", usedPercent: used,
                                   resetsAt: nil, durationSeconds: 604800, isModelSpecific: modelOnly))
    }
    return ClaudeProxyAccount(id: "first", label: "One", snapshot: ProviderSnapshot(provider: .claude, plan: nil, windows: windows), error: error)
}

@Test func weeklyMenuShowsRemainingWeeklyShareRatherThanSessionOrModelLimits() {
    let item = ClaudeWeeklyMenuItem(account: weeklyAccount(used: 96.6))
    #expect(item.percent == 3)
    #expect(item.id == "first")
    #expect(item.label == "One")
    #expect(item.stale == false)
    #expect(ClaudeWeeklyMenuItem(account: weeklyAccount(used: 25, modelOnly: true)).percent == nil)
    #expect(ClaudeWeeklyMenuItem(account: weeklyAccount(used: nil)).percent == nil)
}

@Test func weeklyMenuNeverPresentsACachedFailedReadingAsFresh() {
    for error: ProviderError in [.loginExpired, .network("offline"), .rateLimited(retryAfter: 300)] {
        let item = ClaudeWeeklyMenuItem(account: weeklyAccount(used: 25, error: error))
        #expect(item.percent == nil)
        #expect(item.stale)
    }
    #expect(ClaudeWeeklyMenuItem(account: weeklyAccount(used: 0)).percent == 100)
    #expect(ClaudeWeeklyMenuItem(account: weeklyAccount(used: 100)).percent == 0)
}

@Test func weeklyMenuKeepsBothAccountsEvenWhenOneHasNoReading() {
    let unavailable = ClaudeProxyAccount(id: "missing", label: "Missing", snapshot: nil, error: .loginExpired)
    let items = [unavailable, weeklyAccount(used: 40)].map(ClaudeWeeklyMenuItem.init)
    #expect(items.map(\.id) == ["missing", "first"])
    #expect(items.map(\.percent) == [nil, 60])
}
