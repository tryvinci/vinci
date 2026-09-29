import Cocoa
import WebKit

let htmlStudioURL =
  ProcessInfo.processInfo.environment["VINCI_STUDIO_HTML_URL"] ?? "http://127.0.0.1:4310/studio"
let defaultStudioURL =
  ProcessInfo.processInfo.environment["VINCI_STUDIO_URL"] ?? "http://127.0.0.1:4311"

@main
enum VinciStudio {
  static func main() {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.regular)
    app.run()
  }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
  let window = NSWindow(
    contentRect: NSRect(x: 0, y: 0, width: 1280, height: 800),
    styleMask: [.titled, .closable, .miniaturizable, .resizable],
    backing: .buffered,
    defer: false
  )
  var webView: WKWebView!
  var triedHtml = false

  func applicationDidFinishLaunching(_ notification: Notification) {
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .default()
    webView = WKWebView(frame: window.contentView?.bounds ?? .zero, configuration: config)
    webView.navigationDelegate = self
    webView.autoresizingMask = [.width, .height]
    window.contentView = webView
    window.title = "Vinci Studio"
    window.center()
    window.makeKeyAndOrderFront(nil)
    NSApp.activate(ignoringOtherApps: true)
    loadStudio(defaultStudioURL)
  }

  func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
    true
  }

  func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
    fallbackOrOffline()
  }

  func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
    fallbackOrOffline()
  }

  private func loadStudio(_ value: String) {
    guard let url = URL(string: value) else { return }
    webView.load(URLRequest(url: url))
  }

  private func fallbackOrOffline() {
    if !triedHtml && defaultStudioURL != htmlStudioURL {
      triedHtml = true
      loadStudio(htmlStudioURL)
      return
    }
    showOffline()
  }

  private func showOffline() {
    let html = """
    <html><body style="font-family:-apple-system,sans-serif;background:#09090b;color:#fafafa;padding:2rem">
    <h1>Start Vinci Studio</h1>
    <p>This window loads TypeScript Studio at <code>\(defaultStudioURL)</code>, then HTML <code>\(htmlStudioURL)</code>.</p>
    <pre>cd vinci && source .venv/bin/activate && ./scripts/vinci init --demo && ./scripts/vinci studio</pre>
    <p>Override with <code>VINCI_STUDIO_URL</code> or <code>VINCI_STUDIO_HTML_URL</code>.</p>
    </body></html>
    """
    webView.loadHTMLString(html, baseURL: nil)
  }
}
