import Foundation

/// A limits-only feed. The bridge owns access to CLIProxyAPI; no provider token reaches the app.
public struct ClaudeProxyClient: Sendable {
    public let baseURL: URL
    private let session: URLSession

    public init(url: String, session: URLSession = .tinybar) throws {
        guard let url = URL(string: url.trimmingCharacters(in: .whitespacesAndNewlines)),
              let host = url.host, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil,
              url.scheme == "https" || (url.scheme == "http" && ["127.0.0.1", "localhost", "[::1]", "::1"].contains(host))
        else { throw ProviderError.unexpected("Use HTTPS or a local SSH tunnel for the Claude accounts URL.") }
        baseURL = url
        self.session = session
    }

    public func fetch() async throws -> [ClaudeProxyAccount] {
        let request = URLRequest(
            url: baseURL.appendingPathComponent("v1/claude/accounts"),
            cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 45)
        let data = try await HTTP.send(request, session: session, providerName: "Claude accounts")
        return try Self.decode(data)
    }

    static func decode(_ data: Data) throws -> [ClaudeProxyAccount] {
        do {
            let response = try JSONDecoder().decode(Response.self, from: data)
            guard response.schemaVersion == 1, response.accounts.count <= 100 else {
                throw ProviderError.unexpected("Unsupported Claude accounts response.")
            }
            var ids = Set<String>()
            return try response.accounts.map { account in
                guard !account.id.isEmpty, account.id.count <= 128,
                      account.id.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }),
                      ids.insert(account.id).inserted, !account.label.trimmingCharacters(in: .whitespaces).isEmpty,
                      let fetchedAt = parseISODate(account.fetchedAt), account.usage != nil || account.error != nil
                else { throw ProviderError.unexpected("Invalid Claude account response.") }
                let snapshot = account.usage.map { usage -> ProviderSnapshot in
                    var snapshot = ClaudeUsageAPI.snapshot(from: usage, plan: account.plan, now: fetchedAt)
                    snapshot.accountID = account.id
                    return snapshot
                }
                let error: ProviderError? = account.error.map {
                    switch $0.code {
                    case "login_expired": .loginExpired
                    case "rate_limited": .rateLimited(retryAfter: $0.retryAfterSeconds)
                    default: .unexpected("Could not read this account's limits. Check CLIProxyAPI on the server.")
                    }
                }
                return ClaudeProxyAccount(id: account.id, label: account.label, snapshot: snapshot, error: error)
            }
        } catch let error as ProviderError { throw error }
        catch { throw ProviderError.unexpected("Unexpected Claude accounts response.") }
    }

    private struct Response: Decodable {
        var schemaVersion: Int
        var accounts: [Account]
        enum CodingKeys: String, CodingKey { case schemaVersion = "schema_version", accounts }
    }

    private struct Account: Decodable {
        var id: String
        var label: String
        var plan: String?
        var fetchedAt: String
        var usage: ClaudeUsageAPI.UsageResponse?
        var error: AccountError?
        enum CodingKeys: String, CodingKey { case id, label, plan, usage, error; case fetchedAt = "fetched_at" }
    }

    private struct AccountError: Decodable {
        var code: String
        var retryAfterSeconds: Double?
        enum CodingKeys: String, CodingKey { case code; case retryAfterSeconds = "retry_after_seconds" }
    }
}

public struct ClaudeProxyAccount: Identifiable, Sendable {
    public var id: String
    public var label: String
    public var snapshot: ProviderSnapshot?
    public var error: ProviderError?

    public init(id: String, label: String, snapshot: ProviderSnapshot?, error: ProviderError?) {
        self.id = id
        self.label = label
        self.snapshot = snapshot
        self.error = error
    }

    /// Keep the last reading on a failed refresh; remove accounts only after a successful list.
    public static func merging(_ next: [Self], previous: [Self]) -> [Self] {
        let old = Dictionary(previous.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        return next.map { account in
            var account = account
            if account.error != nil, account.snapshot == nil { account.snapshot = old[account.id]?.snapshot }
            return account
        }
    }
}
