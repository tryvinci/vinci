import Cocoa
import CryptoKit
import WebKit

@main
enum VinciStudio {
  static func main() {
    let args = CommandLine.arguments
    var smokeReport: String?
    var smokeScreenshot: String?
    var smokeHome: String?
    var smokeDownload: String?
    var smokeState: String?
    var smokeRelaunchReport: String?
    var smokeRelaunch = false
    var index = 1
    while index < args.count {
      let arg = args[index]
      switch arg {
      case "--smoke-report" where index + 1 < args.count:
        smokeReport = args[index + 1]
        index += 2
      case "--smoke-screenshot" where index + 1 < args.count:
        smokeScreenshot = args[index + 1]
        index += 2
      case "--smoke-home" where index + 1 < args.count:
        smokeHome = args[index + 1]
        index += 2
      case "--smoke-download" where index + 1 < args.count:
        smokeDownload = args[index + 1]
        index += 2
      case "--smoke-state" where index + 1 < args.count:
        smokeState = args[index + 1]
        index += 2
      case "--smoke-relaunch-report" where index + 1 < args.count:
        smokeRelaunchReport = args[index + 1]
        index += 2
      case "--smoke-relaunch-verify":
        smokeRelaunch = true
        index += 1
      default:
        index += 1
      }
    }
    let app = NSApplication.shared
    let delegate = AppDelegate()
    delegate.smokeReportPath = smokeReport
    delegate.smokeScreenshotPath = smokeScreenshot
    delegate.smokeHomeOverride = smokeHome
    delegate.smokeDownloadPath = smokeDownload
    delegate.smokeStatePath = smokeState
    delegate.smokeRelaunchReportPath = smokeRelaunchReport
    delegate.smokeRelaunchVerify = smokeRelaunch
    delegate.smokeMode = smokeReport != nil
    app.delegate = delegate
    app.setActivationPolicy(delegate.smokeMode ? .accessory : .regular)
    app.run()
  }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate,
  WKDownloadDelegate {
  let window = NSWindow(
    contentRect: NSRect(x: 0, y: 0, width: 1280, height: 800),
    styleMask: [.titled, .closable, .miniaturizable, .resizable],
    backing: .buffered,
    defer: false
  )
  var webView: WKWebView!
  var daemon: ChildProcess?
  var studio: ChildProcess?
  var bridgeToken = ""
  var studioSession = ""
  var launchNonce = ""
  var daemonPort = 0
  var studioPort = 0
  var dataHome = ""
  var instanceLock: FileHandle?
  var smokeReportPath: String?
  var smokeScreenshotPath: String?
  var smokeHomeOverride: String?
  var smokeDownloadPath: String?
  var smokeStatePath: String?
  var smokeRelaunchReportPath: String?
  var smokeRelaunchVerify = false
  var smokeMode = false
  var smokeRunner: SmokeRunner?
  var studioReadinessVerified = false
  var smokeExportDownloadDone = false
  var smokeExportByteCount = 0

  func applicationDidFinishLaunching(_ notification: Notification) {
    if let smokeHomeOverride, !smokeHomeOverride.isEmpty {
      dataHome = smokeHomeOverride
    } else {
      dataHome = resolveDataHome()
    }
    if !acquireSingleInstance() {
      smokeFatal("another studio instance holds lock")
      return
    }
    setupMenus()
    bridgeToken = UUID().uuidString.replacingOccurrences(of: "-", with: "")
    studioSession = UUID().uuidString.replacingOccurrences(of: "-", with: "")
    launchNonce = UUID().uuidString.replacingOccurrences(of: "-", with: "")
    ensureDirectories()
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .default()
    webView = WKWebView(frame: window.contentView?.bounds ?? .zero, configuration: config)
    webView.navigationDelegate = self
    webView.uiDelegate = self
    webView.autoresizingMask = [.width, .height]
    window.contentView = webView
    window.title = "Vinci Studio"
    if smokeMode {
      window.setFrameOrigin(NSPoint(x: 0, y: 0))
      window.makeKeyAndOrderFront(nil)
    } else {
      window.center()
      window.makeKeyAndOrderFront(nil)
      NSApp.activate(ignoringOtherApps: true)
    }
    showStarting("Starting Vinci…")
    startServices()
  }

  func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

  func applicationWillTerminate(_ notification: Notification) {
    stopServices()
    instanceLock?.closeFile()
  }

  func smokeFatal(_ message: String) {
    if smokeMode, let path = smokeReportPath {
      SmokeRunner.writeFailureReport(
        path: path,
        screenshotPath: smokeScreenshotPath,
        detail: message,
        gitSha: ProcessInfo.processInfo.environment["VINCI_GIT_SHA"] ?? ""
      )
    }
    stopServices()
    fputs("smoke fatal: \(message)\n", stderr)
    exit(1)
  }

  private func bundleResource(_ subpath: String) -> String {
    Bundle.main.resourcePath!.appending("/").appending(subpath)
  }

  private func resolveDataHome() -> String {
    if let override = ProcessInfo.processInfo.environment["VINCI_HOME"], !override.isEmpty {
      return (override as NSString).expandingTildeInPath
    }
    return NSHomeDirectory() + "/.vinci"
  }

  private func filteredChildEnv(extra: [String: String]) -> [String: String] {
    let allow = Set(["HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE"])
    var out: [String: String] = [:]
    for (key, value) in ProcessInfo.processInfo.environment where allow.contains(key) {
      out[key] = value
    }
    for (key, value) in extra {
      out[key] = value
    }
    return out
  }

  func readinessProof() -> String {
    let key = SymmetricKey(data: Data(studioSession.utf8))
    let mac = HMAC<SHA256>.authenticationCode(for: Data(launchNonce.utf8), using: key)
    return mac.map { String(format: "%02x", $0) }.joined()
  }

  func releaseInstanceLock() {
    instanceLock?.closeFile()
    instanceLock = nil
  }

  private func injectSessionCookie(completion: @escaping () -> Void) {
    var props: [HTTPCookiePropertyKey: Any] = [
      .domain: "127.0.0.1",
      .path: "/",
      .name: "vinci_studio_session",
      .value: studioSession,
      .discard: "TRUE",
      .version: "0",
    ]
    props[.init("HttpOnly")] = "TRUE"
    if #available(macOS 10.15, *) {
      props[.sameSitePolicy] = HTTPCookieStringPolicy.sameSiteStrict
    }
    guard let cookie = HTTPCookie(properties: props) else {
      completion()
      return
    }
    webView.configuration.websiteDataStore.httpCookieStore.setCookie(cookie) {
      completion()
    }
  }

  private func ensureDirectories() {
    try? FileManager.default.createDirectory(atPath: dataHome, withIntermediateDirectories: true)
    let logs = NSHomeDirectory() + "/Library/Logs/Vinci"
    try? FileManager.default.createDirectory(atPath: logs, withIntermediateDirectories: true)
  }

  private func acquireSingleInstance() -> Bool {
    if ProcessInfo.processInfo.environment["VINCI_SMOKE_RELAY"] == "1" {
      return true
    }
    let lockPath = dataHome + "/.studio-instance.lock"
    let fd = open(lockPath, O_CREAT | O_RDWR, 0o600)
    if fd < 0 { return true }
    if flock(fd, LOCK_EX | LOCK_NB) != 0 {
      close(fd)
      if smokeMode {
        return false
      }
      let alert = NSAlert()
      alert.messageText = "Vinci Studio is already running"
      alert.informativeText = "Use the existing window or quit the other copy first."
      alert.runModal()
      return false
    }
    instanceLock = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
    return true
  }

  private func setupMenus() {
    let mainMenu = NSMenu()
    let appItem = NSMenuItem()
    mainMenu.addItem(appItem)
    let appMenu = NSMenu()
    appItem.submenu = appMenu
    appMenu.addItem(withTitle: "About Vinci Studio", action: #selector(showAbout), keyEquivalent: "")
    appMenu.addItem(withTitle: "Open Data Folder", action: #selector(openDataFolder), keyEquivalent: "")
    appMenu.addItem(withTitle: "Open Logs", action: #selector(openLogs), keyEquivalent: "")
    appMenu.addItem(NSMenuItem.separator())
    appMenu.addItem(withTitle: "Quit Vinci Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    NSApp.mainMenu = mainMenu
  }

  @objc private func showAbout() {
    let alert = NSAlert()
    alert.messageText = "Vinci Studio (alpha)"
    alert.informativeText = "Unsigned arm64 alpha.\nData: \(dataHome)"
    alert.runModal()
  }

  @objc private func openDataFolder() {
    NSWorkspace.shared.open(URL(fileURLWithPath: dataHome))
  }

  @objc private func openLogs() {
    NSWorkspace.shared.open(URL(fileURLWithPath: NSHomeDirectory() + "/Library/Logs/Vinci"))
  }

  private func startServices() {
    stopServices()
    do {
      try startDaemon()
      try startStudioServer()
      waitForStudio()
    } catch {
      let msg = error.localizedDescription
      if smokeMode {
        smokeFatal(msg)
      } else {
        showError(msg)
      }
    }
  }

  private func startDaemon() throws {
    let python = bundleResource("runtime/bin/python3")
    let env = filteredChildEnv(extra: [
      "VINCI_HOME": dataHome,
      "VINCI_ALLOW_LIVE_SPEND": "0",
      "VINCI_BRIDGE_TOKEN": bridgeToken,
      "VINCI_FFMPEG": bundleResource("bin/ffmpeg"),
      "VINCI_FFPROBE": bundleResource("bin/ffprobe"),
      "PATH": bundleResource("bin"),
      "PYTHONDONTWRITEBYTECODE": "1",
    ])
    let logPath = NSHomeDirectory() + "/Library/Logs/Vinci/daemon.log"
    let proc = ChildProcess(
      executable: python,
      args: [
        "-m", "vinci_daemon.app",
        "--host", "127.0.0.1",
        "--port", "0",
        "--desktop",
        "--launch-nonce", launchNonce,
        "--parent-pid", String(ProcessInfo.processInfo.processIdentifier),
      ],
      env: env,
      logPath: logPath
    )
    try proc.start()
    daemon = proc
    guard let ready = proc.readReadyLine(timeout: 25) else {
      throw NSError(domain: "Vinci", code: 1, userInfo: [NSLocalizedDescriptionKey: "Daemon READY timeout"])
    }
    let parts = ready.split(separator: " ")
    guard parts.count >= 3, parts[0] == "READY" else {
      throw NSError(domain: "Vinci", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid READY line"])
    }
    daemonPort = Int(parts[1]) ?? 0
    let nonce = String(parts[2])
    guard nonce == launchNonce else {
      throw NSError(domain: "Vinci", code: 3, userInfo: [NSLocalizedDescriptionKey: "Foreign daemon nonce"])
    }
    guard verifyDaemonHealth(retries: 40) else {
      throw NSError(domain: "Vinci", code: 4, userInfo: [NSLocalizedDescriptionKey: "Daemon health failed"])
    }
  }

  private func verifyDaemonHealth(retries: Int) -> Bool {
    let url = URL(string: "http://127.0.0.1:\(daemonPort)/healthz")!
    for _ in 0..<retries {
      guard let data = try? Data(contentsOf: url),
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
      else {
        Thread.sleep(forTimeInterval: 0.05)
        continue
      }
      guard json["desktop"] as? String == "1" else { return false }
      guard json["launch_nonce"] as? String == launchNonce else { return false }
      if let pidStr = json["pid"] as? String, let pid = Int(pidStr), pid != daemon?.pid ?? 0 {
        return false
      }
      if json["status"] as? String == "ok" { return true }
    }
    return false
  }

  private func startStudioServer() throws {
    let node = bundleResource("studio/node")
    let launcher = bundleResource("studio/studio-launcher.cjs")
    let script = FileManager.default.fileExists(atPath: launcher) ? launcher : bundleResource("studio/server.js")
    studioPort = pickFreePort()
    let origin = "http://127.0.0.1:\(studioPort)"
    let env = filteredChildEnv(extra: [
      "PORT": String(studioPort),
      "HOSTNAME": "127.0.0.1",
      "VINCI_DAEMON_URL": "http://127.0.0.1:\(daemonPort)",
      "VINCI_BRIDGE_TOKEN": bridgeToken,
      "VINCI_STUDIO_SESSION": studioSession,
      "VINCI_STUDIO_HOST": "127.0.0.1:\(studioPort)",
      "VINCI_STUDIO_ORIGIN": origin,
      "VINCI_LAUNCH_NONCE": launchNonce,
      "VINCI_PARENT_PID": String(ProcessInfo.processInfo.processIdentifier),
    ])
    let logPath = NSHomeDirectory() + "/Library/Logs/Vinci/studio.log"
    let proc = ChildProcess(
      executable: node,
      args: [script],
      env: env,
      logPath: logPath,
      cwd: bundleResource("studio")
    )
    try proc.start()
    studio = proc
  }

  private func verifyStudioReadiness(attempt: Int, completion: @escaping (Bool) -> Void) {
    if attempt >= 80 {
      completion(false)
      return
    }
    guard studio?.isRunning == true else {
      completion(false)
      return
    }
    let url = URL(string: "http://127.0.0.1:\(studioPort)/api/studio-readiness")!
    let expected = readinessProof()
    var req = URLRequest(url: url)
    req.setValue(bridgeToken, forHTTPHeaderField: "X-Vinci-Bridge-Token")
    URLSession.shared.dataTask(with: req) { data, resp, _ in
      let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
      var ok = false
      if code == 200,
         let data,
         let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
         json["proof"] as? String == expected,
         json["launch_nonce"] as? String == launchNonce {
        ok = true
      }
      if ok {
        completion(true)
        return
      }
      DispatchQueue.global().asyncAfter(deadline: .now() + 0.2) {
        self.verifyStudioReadiness(attempt: attempt + 1, completion: completion)
      }
    }.resume()
  }

  private func waitForStudio() {
    verifyStudioReadiness(attempt: 0) { ready in
      DispatchQueue.main.async {
        if !ready {
          if self.smokeMode {
            self.smokeFatal("Studio readiness/HMAC failed")
          } else {
            self.showError("Studio readiness failed")
          }
          return
        }
        self.studioReadinessVerified = true
        let url = "http://127.0.0.1:\(self.studioPort)/"
        self.injectSessionCookie {
          self.loadStudio(url)
        }
      }
    }
  }

  private func loadStudio(_ value: String) {
    guard let url = URL(string: value) else { return }
    webView.load(URLRequest(url: url))
  }

  private func showStarting(_ message: String) {
    webView.loadHTMLString(
      """
      <html><body style="font-family:-apple-system,sans-serif;background:#09090b;color:#fafafa;padding:2rem">
      <h1>\(message)</h1></body></html>
      """,
      baseURL: nil
    )
  }

  private func showError(_ message: String) {
    webView.loadHTMLString(
      """
      <html><body style="font-family:-apple-system,sans-serif;background:#09090b;color:#fafafa;padding:2rem">
      <h1>Could not start Vinci Studio</h1><p>\(message)</p></body></html>
      """,
      baseURL: nil
    )
  }

  func stopServices() {
    studio?.terminateAndWait()
    daemon?.terminateAndWait()
    studio = nil
    daemon = nil
  }

  func bundleResourcePath(_ subpath: String) -> String {
    bundleResource(subpath)
  }

  func webView(
    _ webView: WKWebView,
    decidePolicyFor navigationAction: WKNavigationAction,
    preferences: WKWebpagePreferences,
    decisionHandler: @escaping (WKNavigationActionPolicy, WKWebpagePreferences) -> Void
  ) {
    if navigationAction.shouldPerformDownload {
      decisionHandler(.download, preferences)
    } else {
      decisionHandler(.allow, preferences)
    }
  }

  func webView(
    _ webView: WKWebView,
    runOpenPanelWith parameters: WKOpenPanelParameters,
    initiatedByFrame frame: WKFrameInfo,
    completionHandler: @escaping ([URL]?) -> Void
  ) {
    let panel = NSOpenPanel()
    panel.allowsMultipleSelection = parameters.allowsMultipleSelection
    panel.canChooseDirectories = parameters.allowsDirectories
    panel.canChooseFiles = true
    panel.begin { result in
      completionHandler(result == .OK ? panel.urls : nil)
    }
  }

  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    guard let url = webView.url?.absoluteString,
          url.contains("127.0.0.1:\(studioPort)") else { return }
    guard smokeMode, smokeRunner == nil, let report = smokeReportPath else { return }
    let shot = smokeScreenshotPath ?? (NSTemporaryDirectory() + "vinci-smoke.png")
    let reportPath = smokeRelaunchVerify ? (smokeRelaunchReportPath ?? report) : report
    let runner = SmokeRunner(
      reportPath: reportPath,
      screenshotPath: shot,
      relaunchOnly: smokeRelaunchVerify,
      statePath: smokeStatePath,
      downloadPath: smokeDownloadPath,
      relaunchReportPath: smokeRelaunchVerify ? nil : smokeRelaunchReportPath
    )
    smokeRunner = runner
    runner.runAfterStudioLoad(on: self)
  }

  func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
    download.delegate = self
  }

  func download(_ download: WKDownload, didFinishWith error: Error?) {
    guard smokeMode, error == nil, let path = smokeDownloadPath else { return }
    if let attrs = try? FileManager.default.attributesOfItem(atPath: path),
       let size = attrs[.size] as? NSNumber {
      smokeExportByteCount = size.intValue
      smokeExportDownloadDone = size.intValue > 0
    }
  }

  func download(
    _ download: WKDownload,
    decideDestinationUsing response: URLResponse,
    suggestedFilename: String,
    completionHandler: @escaping (URL?) -> Void
  ) {
    if smokeMode, let path = smokeDownloadPath, !path.isEmpty {
      try? FileManager.default.removeItem(atPath: path)
      completionHandler(URL(fileURLWithPath: path))
      return
    }
    let panel = NSSavePanel()
    panel.nameFieldStringValue = suggestedFilename
    panel.begin { result in
      completionHandler(result == .OK ? panel.url : nil)
    }
  }
}

private func shellQuote(_ value: String) -> String {
  "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

private func childPids(of parent: pid_t) -> [pid_t] {
  let proc = Process()
  let pipe = Pipe()
  proc.executableURL = URL(fileURLWithPath: "/bin/sh")
  proc.arguments = ["-c", "pgrep -P \(parent) 2>/dev/null || true"]
  proc.standardOutput = pipe
  proc.standardError = Pipe()
  do {
    try proc.run()
    proc.waitUntilExit()
  } catch {
    return []
  }
  let data = pipe.fileHandleForReading.readDataToEndOfFile()
  guard let text = String(data: data, encoding: .utf8) else { return [] }
  return text.split(separator: "\n").compactMap { Int32($0.trimmingCharacters(in: .whitespaces)) }
}

final class ChildProcess {
  let executable: String
  let args: [String]
  let env: [String: String]
  let logPath: String
  let cwd: String?
  private var process: Process?
  private var stdoutPipe: Pipe?
  private var stderrPipe: Pipe?
  private var logHandle: FileHandle?
  private let readyLock = NSLock()
  private var readyBuffer = Data()
  private var readyLine: String?
  var pid: Int32 { process?.processIdentifier ?? 0 }
  var isRunning: Bool { process?.isRunning ?? false }

  init(
    executable: String,
    args: [String],
    env: [String: String],
    logPath: String,
    cwd: String? = nil
  ) {
    self.executable = executable
    self.args = args
    self.env = env
    self.logPath = logPath
    self.cwd = cwd
  }

  func start() throws {
    let proc = Process()
    let cmd = ([executable] + args).map(shellQuote).joined(separator: " ")
    proc.executableURL = URL(fileURLWithPath: "/bin/bash")
    let cdPrefix = cwd.map { "cd \(shellQuote($0)) && " } ?? ""
    proc.arguments = ["-c", "\(cdPrefix)exec setsid \(cmd)"]
    proc.environment = env
    let outPipe = Pipe()
    let errPipe = Pipe()
    proc.standardOutput = outPipe
    proc.standardError = errPipe
    if FileManager.default.fileExists(atPath: logPath) {
      try? FileManager.default.removeItem(atPath: logPath)
    }
    FileManager.default.createFile(atPath: logPath, contents: nil)
    logHandle = FileHandle(forWritingAtPath: logPath)
    try proc.run()
    process = proc
    stdoutPipe = outPipe
    stderrPipe = errPipe
    outPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
      let chunk = handle.availableData
      if chunk.isEmpty { return }
      self?.logHandle?.write(chunk)
      self?.appendReady(chunk)
    }
    errPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
      let chunk = handle.availableData
      if chunk.isEmpty { return }
      self?.logHandle?.write(chunk)
    }
  }

  private func appendReady(_ chunk: Data) {
    readyLock.lock()
    readyBuffer.append(chunk)
    if readyLine == nil, let text = String(data: readyBuffer, encoding: .utf8) {
      for line in text.components(separatedBy: "\n") where line.hasPrefix("READY ") {
        let parts = line.split(separator: " ")
        if parts.count >= 3 {
          readyLine = line.trimmingCharacters(in: .whitespacesAndNewlines)
          break
        }
      }
    }
    readyLock.unlock()
  }

  func readReadyLine(timeout: TimeInterval) -> String? {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
      readyLock.lock()
      let line = readyLine
      readyLock.unlock()
      if let line { return line }
      Thread.sleep(forTimeInterval: 0.05)
    }
    return nil
  }

  func terminateAndWait() {
    guard let proc = process else { return }
    let pid = proc.processIdentifier
    let pgid = getpgid(pid)
    if pgid > 0 {
      kill(-pgid, SIGTERM)
    } else if proc.isRunning {
      proc.terminate()
    }
    let deadline = Date().addingTimeInterval(8)
    while proc.isRunning && Date() < deadline {
      Thread.sleep(forTimeInterval: 0.1)
    }
    if proc.isRunning {
      if pgid > 0 {
        kill(-pgid, SIGKILL)
      } else {
        kill(pid, SIGKILL)
      }
    }
    stdoutPipe?.fileHandleForReading.readabilityHandler = nil
    stderrPipe?.fileHandleForReading.readabilityHandler = nil
    _ = stdoutPipe?.fileHandleForReading.readDataToEndOfFile()
    _ = stderrPipe?.fileHandleForReading.readDataToEndOfFile()
    logHandle?.closeFile()
    logHandle = nil
    process = nil
  }

  func descendantPids() -> [pid_t] {
    let root = pid
    var seen = Set<pid_t>()
    var queue = childPids(of: root)
    while !queue.isEmpty {
      let next = queue.removeFirst()
      if seen.contains(next) { continue }
      seen.insert(next)
      queue.append(contentsOf: childPids(of: next))
    }
    return Array(seen)
  }
}

func pickFreePort() -> Int {
  let fd = Darwin.socket(AF_INET, SOCK_STREAM, 0)
  defer { Darwin.close(fd) }
  var addr = sockaddr_in()
  addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
  addr.sin_family = sa_family_t(AF_INET)
  addr.sin_port = 0
  addr.sin_addr.s_addr = inet_addr("127.0.0.1")
  let bindOk = withUnsafePointer(to: &addr) {
    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
      Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
    }
  }
  if bindOk != 0 { return 4311 }
  var name = sockaddr_in()
  var len = socklen_t(MemoryLayout<sockaddr_in>.size)
  withUnsafeMutablePointer(to: &name) { ptr in
    ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
      Darwin.getsockname(fd, sa, &len)
    }
  }
  return Int(Darwin.ntohs(name.sin_port))
}
