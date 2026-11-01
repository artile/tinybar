import Foundation
import Testing
@testable import TinybarCore

private let proxyFixture = Data(#"""
{"schema_version":1,"accounts":[
  {"id":"first","label":"One","fetched_at":"2030-01-01T00:00:00Z","usage":{
    "five_hour":{"utilization":91,"resets_at":"2030-01-01T05:00:00Z"},
    "seven_day":{"utilization":20,"resets_at":"2030-01-08T00:00:00Z"}}},
  {"id":"second","label":"Two","fetched_at":"2030-01-01T00:00:00Z","usage":{
    "five_hour":{"utilization":96,"resets_at":"2030-01-01T05:00:00Z"}}}
]}
"""#.utf8)

private final class ClaudeProxyFixture: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}
    override func startLoading() {
        #expect(request.httpMethod == "GET")
        #expect(request.url?.path == "/v1/claude/accounts")
        #expect(request.value(forHTTPHeaderField: "Authorization") == nil)
        #expect(request.httpBody == nil)
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: proxyFixture)
        client?.urlProtocolDidFinishLoading(self)
    }
}

@Test func proxyFeedUsesReadOnlyRouteWithoutProviderOrManagementCredentials() async throws {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [ClaudeProxyFixture.self]
    let session = URLSession(configuration: config)
    defer { session.invalidateAndCancel() }
    let accounts = try await ClaudeProxyClient(url: "http://127.0.0.1:18767", session: session).fetch()
    #expect(accounts.count == 2)
    #expect(accounts[0].snapshot?.accountID == "first")
    #expect(accounts[0].snapshot?.windows.first?.remainingPercent == 9)
}

@Test func proxyRejectsCleartextRemoteAndAmbiguousAccountLists() throws {
    for url in ["http://vps:18767", "http://user:secret@localhost", "https://host.invalid?token=secret", "file:///tmp/accounts"] {
        #expect(throws: ProviderError.self) { try ClaudeProxyClient(url: url) }
    }
    for wire in [
        #"{"schema_version":2,"accounts":[]}"#,
        String(decoding: proxyFixture, as: UTF8.self).replacingOccurrences(of: #""id":"second""#, with: #""id":"first""#),
        String(decoding: proxyFixture, as: UTF8.self).replacingOccurrences(of: #""id":"first""#, with: #""id":"bad/account""#),
        String(decoding: proxyFixture, as: UTF8.self).replacingOccurrences(of: "2030-01-01T00:00:00Z", with: "invalid")
    ] {
        #expect(throws: ProviderError.self) { try ClaudeProxyClient.decode(Data(wire.utf8)) }
    }
}

@Test func accountFailuresKeepOnlyTheirOwnPreviousReadingAndSuccessfulListsRemoveAccounts() throws {
    let previous = try ClaudeProxyClient.decode(proxyFixture)
    let failure = try ClaudeProxyClient.decode(Data(#"""
    {"schema_version":1,"accounts":[{"id":"first","label":"Renamed","fetched_at":"2030-01-01T00:05:00Z",
      "error":{"code":"login_expired"}}]}
    """#.utf8))
    let merged = ClaudeProxyAccount.merging(failure, previous: previous)
    #expect(merged.count == 1)
    #expect(merged[0].label == "Renamed")
    #expect(merged[0].error == .loginExpired)
    #expect(merged[0].snapshot == previous[0].snapshot)
    #expect(ClaudeProxyAccount.merging([], previous: previous).isEmpty)
    let newAccount = ClaudeProxyAccount(id: "new", label: "New", snapshot: nil, error: .loginExpired)
    #expect(ClaudeProxyAccount.merging([newAccount], previous: previous)[0].snapshot == nil)
}

private func selections(_ accounts: [ClaudeProxyAccount], staleID: String? = nil) -> [LimitSelection] {
    accounts.flatMap { account in
        (account.snapshot?.windows ?? []).map {
            LimitSelection(provider: .claude, accountID: account.id, accountName: account.label,
                           window: $0, fetchedAt: account.snapshot!.fetchedAt, stale: account.id == staleID)
        }
    }
}

@Test func pinAndAutoDistinguishAccountsWithTheSameWindowID() throws {
    let candidates = selections(try ClaudeProxyClient.decode(proxyFixture))
    let firstKey = LimitSelection.key(provider: .claude, accountID: "first", windowID: "session")
    let secondKey = LimitSelection.key(provider: .claude, accountID: "second", windowID: "session")
    #expect(firstKey != secondKey)
    #expect(LimitSelection.choose(candidates, pinnedKey: firstKey)?.accountID == "first")
    #expect(LimitSelection.choose(candidates, pinnedKey: secondKey)?.accountID == "second")
    #expect(LimitSelection.choose(candidates, pinnedKey: nil)?.accountID == "second")
    #expect(LimitSelection.choose(candidates, pinnedKey: "removed/session")?.accountID == "second")
    #expect(LimitSelection.key(provider: .claude, windowID: "session") == "claude/session")
}

@Test func autoPrefersFreshAccountsButAnExplicitPinCanKeepAStaleAccount() throws {
    let candidates = selections(try ClaudeProxyClient.decode(proxyFixture), staleID: "second")
    #expect(LimitSelection.choose(candidates, pinnedKey: nil)?.accountID == "first")
    #expect(LimitSelection.choose(candidates, pinnedKey: "claude@second/session")?.stale == true)
}

@Test func alertsAreSeparateForEachAccountAndSurviveRestarts() throws {
    let accounts = try ClaudeProxyClient.decode(proxyFixture)
    var planner = LimitAlertPlanner()
    let first = try #require(accounts[0].snapshot)
    var second = try #require(accounts[1].snapshot)
    #expect(planner.evaluate(first).count == 1)
    #expect(planner.evaluate(second).count == 1)
    var restored = try JSONDecoder().decode(LimitAlertPlanner.self, from: JSONEncoder().encode(planner))
    #expect(restored.evaluate(first).isEmpty)
    #expect(restored.evaluate(second).isEmpty)
    second.windows[0].usedPercent = 0
    #expect(restored.evaluate(second).count == 1)
    #expect(restored.evaluate(first).isEmpty)
}

@Test func proxyMapsRateLimitsAndServerFailuresWithoutLeakingMessages() throws {
    let wire = Data(#"""
    {"schema_version":1,"accounts":[{"id":"first","label":"One","fetched_at":"2030-01-01T00:00:00Z",
      "error":{"code":"rate_limited","retry_after_seconds":1200,"message":"SECRET"}},
      {"id":"second","label":"Two","fetched_at":"2030-01-01T00:00:00Z",
      "error":{"code":"upstream_error","message":"SECRET"}}]}
    """#.utf8)
    let accounts = try ClaudeProxyClient.decode(wire)
    #expect(accounts[0].error == .rateLimited(retryAfter: 1200))
    #expect(accounts[1].error?.localizedDescription.contains("SECRET") == false)
}
