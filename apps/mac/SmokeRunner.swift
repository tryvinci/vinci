import AVFoundation
import Cocoa
import CryptoKit
import WebKit

struct SmokeStep: Codable {
  let name: String
  let ok: Bool
  let status: Int?
  let detail: String
  let at: String
}

struct SmokeReport: Codable {
  var started_at: String
  var finished_at: String
  var app_bundle_sha256: String
  var git_sha: String
  var studio_port: Int
  var daemon_port: Int
  var launch_nonce: String
  var daemon_pid: Int32
  var steps: [SmokeStep]
  var studio_readiness_hmac_ok: Bool
  var studio_hydrated_ui_ok: Bool
  var wk_proxy_mock_image_ok: Bool
  var wk_proxy_mock_video_ok: Bool
  var avfoundation_mp4_decode_ok: Bool
  var wk_video_playback_ok: Bool
  var wk_proxy_receipt_ok: Bool
  var wk_proxy_range_206_ok: Bool
  var wk_download_export_ok: Bool
  var app_relaunch_persistence_ok: Bool
  var foreign_daemon_isolated_ok: Bool
  var quit_descendants_clean_ok: Bool
  var proxy_unauth_denied: Bool
  var proxy_cross_origin_denied: Bool
  var proxy_wrong_host_denied: Bool
  var readiness_no_bridge_denied: Bool
  var readiness_wrong_bridge_denied: Bool
  var hijacked_studio_proof_rejected: Bool
  var token_in_logs: Bool
  var screenshot_png: String
  var export_file_sha256: String
}

final class SmokeRunner {
  weak var delegate: AppDelegate?
  let reportPath: String
  let screenshotPath: String
  let relaunchOnly: Bool
  let statePath: String?
  let downloadPath: String?
  let relaunchReportPath: String?
  var report: SmokeReport
  private let smokeQueue = DispatchQueue(label: "vinci.smoke.workflow", qos: .userInitiated)
  private let finishLock = NSLock()
  private var finished = false
  private var watchdog: DispatchWorkItem?
  private var pendingJobId = ""

  init(
    reportPath: String,
    screenshotPath: String,
    relaunchOnly: Bool,
    statePath: String?,
    downloadPath: String?,
    relaunchReportPath: String? = nil
  ) {
    self.reportPath = reportPath
    self.screenshotPath = screenshotPath
    self.relaunchOnly = relaunchOnly
    self.statePath = statePath
    self.downloadPath = downloadPath
    self.relaunchReportPath = relaunchReportPath
    report = SmokeRunner.emptyReport(screenshotPath: screenshotPath)
  }

  private static func emptyReport(screenshotPath: String) -> SmokeReport {
    SmokeReport(
      started_at: "",
      finished_at: "",
      app_bundle_sha256: "",
      git_sha: ProcessInfo.processInfo.environment["VINCI_GIT_SHA"] ?? "",
      studio_port: 0,
      daemon_port: 0,
      launch_nonce: "",
      daemon_pid: 0,
      steps: [],
      studio_readiness_hmac_ok: false,
      studio_hydrated_ui_ok: false,
      wk_proxy_mock_image_ok: false,
      wk_proxy_mock_video_ok: false,
      avfoundation_mp4_decode_ok: false,
      wk_video_playback_ok: false,
      wk_proxy_receipt_ok: false,
      wk_proxy_range_206_ok: false,
      wk_download_export_ok: false,
      app_relaunch_persistence_ok: false,
      foreign_daemon_isolated_ok: false,
      quit_descendants_clean_ok: false,
      proxy_unauth_denied: false,
      proxy_cross_origin_denied: false,
      proxy_wrong_host_denied: false,
      readiness_no_bridge_denied: false,
      readiness_wrong_bridge_denied: false,
      hijacked_studio_proof_rejected: false,
      token_in_logs: true,
      screenshot_png: screenshotPath,
      export_file_sha256: ""
    )
  }

  static func writeFailureReport(path: String, screenshotPath: String?, detail: String, gitSha: String) {
    var report = emptyReport(screenshotPath: screenshotPath ?? "")
    report.started_at = ISO8601DateFormatter().string(from: Date())
    report.finished_at = report.started_at
    report.git_sha = gitSha
    report.steps = [
      SmokeStep(name: "fatal", ok: false, status: nil, detail: detail, at: report.started_at),
    ]
    if let data = try? JSONEncoder().encode(report) {
      try? data.write(to: URL(fileURLWithPath: path))
    }
  }

  func isoNow() -> String { ISO8601DateFormatter().string(from: Date()) }

  func step(_ name: String, ok: Bool, status: Int? = nil, detail: String = "") {
    report.steps.append(SmokeStep(name: name, ok: ok, status: status, detail: detail, at: isoNow()))
  }

  func bundleSha256() -> String {
    guard let exe = Bundle.main.executableURL,
          let data = try? Data(contentsOf: exe) else { return "" }
    return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
  }

  func runAfterStudioLoad(on app: AppDelegate) {
    report.started_at = isoNow()
    report.app_bundle_sha256 = bundleSha256()
    report.studio_port = app.studioPort
    report.daemon_port = app.daemonPort
    report.launch_nonce = app.launchNonce
    report.daemon_pid = app.daemon?.pid ?? 0
    delegate = app

    report.studio_readiness_hmac_ok = app.studioReadinessVerified
    step("studio_readiness_hmac", ok: report.studio_readiness_hmac_ok)

    let item = DispatchWorkItem { [weak self] in
      self?.finish(ok: false, detail: "smoke watchdog timeout")
    }
    watchdog = item
    smokeQueue.asyncAfter(deadline: .now() + 180, execute: item)

    if relaunchOnly {
      smokeQueue.async {
        self.runSecurityChecks(app: app) {
          self.runRelaunchVerify(app: app)
        }
      }
      return
    }
    smokeQueue.async { self.runMainWorkflow(app: app) }
  }

  private func wkEval(app: AppDelegate, js: String, completion: @escaping (String) -> Void) {
    DispatchQueue.main.async {
      app.webView.callAsyncJavaScript(js, arguments: [:], in: nil, in: .defaultClient) { result in
        self.smokeQueue.async {
          switch result {
          case .success(let value):
            if let str = value as? String {
              completion(str)
            } else if let n = value as? Int {
              completion(String(n))
            } else if let data = try? JSONSerialization.data(withJSONObject: value),
                      let str = String(data: data, encoding: .utf8) {
              completion(str)
            } else {
              completion("")
            }
          case .failure:
            completion("")
          }
        }
      }
    }
  }

  private func wkFetch(
    app: AppDelegate,
    path: String,
    method: String = "GET",
    bodyJson: String? = nil,
    completion: @escaping (String) -> Void
  ) {
    let bodyEsc = (bodyJson ?? "null")
      .replacingOccurrences(of: "\\", with: "\\\\")
      .replacingOccurrences(of: "'", with: "\\'")
    let js = """
    (async () => {
      const opts = { method: '\(method)', credentials: 'include' };
      if ('\(method)' !== 'GET' && '\(method)' !== 'HEAD') {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = '\(bodyEsc)';
      }
      const res = await fetch('/vinci-api\(path)', opts);
      const text = await res.text();
      return JSON.stringify({ status: res.status, body: text });
    })()
    """
    wkEval(app: app, js: js, completion: completion)
  }

  private func parseStatus(_ raw: String) -> (Int, String) {
    guard let data = raw.data(using: .utf8),
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let status = json["status"] as? Int,
          let body = json["body"] as? String else { return (0, "") }
    return (status, body)
  }

  private func httpStatus(
    url: String,
    method: String = "GET",
    headers: [String: String] = [:],
    body: Data? = nil,
    completion: @escaping (Int, Data?) -> Void
  ) {
    var req = URLRequest(url: URL(string: url)!)
    req.httpMethod = method
    for (k, v) in headers { req.setValue(v, forHTTPHeaderField: k) }
    req.httpBody = body
    URLSession.shared.dataTask(with: req) { data, resp, _ in
      let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
      self.smokeQueue.async { completion(code, data) }
    }.resume()
  }

  private func runSecurityChecks(app: AppDelegate, completion: @escaping () -> Void) {
    let base = "http://127.0.0.1:\(app.studioPort)"
    httpStatus(url: base + "/vinci-api/settings") { code, _ in
      report.proxy_unauth_denied = code == 401
      step("proxy_unauth", ok: report.proxy_unauth_denied, status: code)

      httpStatus(
        url: base + "/vinci-api/init",
        method: "POST",
        headers: [
          "Content-Type": "application/json",
          "Origin": "https://evil.example",
          "Cookie": "vinci_studio_session=\(app.studioSession)",
        ],
        body: Data("{\"demo\":true}".utf8)
      ) { cross, _ in
        report.proxy_cross_origin_denied = cross == 403
        step("proxy_cross_origin", ok: report.proxy_cross_origin_denied, status: cross)

        httpStatus(
          url: base + "/vinci-api/settings",
          headers: [
            "Host": "evil.example",
            "Cookie": "vinci_studio_session=\(app.studioSession)",
          ]
        ) { hostCode, _ in
          report.proxy_wrong_host_denied = hostCode == 403
          step("proxy_wrong_host", ok: report.proxy_wrong_host_denied, status: hostCode)

          httpStatus(url: base + "/api/studio-readiness") { noBridge, _ in
            report.readiness_no_bridge_denied = noBridge == 401
            step("readiness_no_bridge", ok: report.readiness_no_bridge_denied, status: noBridge)

            httpStatus(
              url: base + "/api/studio-readiness",
              headers: ["X-Vinci-Bridge-Token": "not-the-bridge-token"]
            ) { wrongBridge, data in
              report.readiness_wrong_bridge_denied = wrongBridge == 401
              step("readiness_wrong_bridge", ok: report.readiness_wrong_bridge_denied, status: wrongBridge)

              let expected = app.readinessProof()
              var rejectedHijack = wrongBridge == 401
              if wrongBridge == 200, let data,
                 let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                 let proof = json["proof"] as? String {
                rejectedHijack = proof != expected
              } else if wrongBridge != 401 {
                rejectedHijack = false
              }
              report.hijacked_studio_proof_rejected = rejectedHijack
              step("hijacked_studio_proof", ok: rejectedHijack)

              httpStatus(
                url: base + "/api/studio-readiness",
                headers: ["X-Vinci-Bridge-Token": app.bridgeToken]
              ) { okCode, data in
                let proofOk = okCode == 200 && {
                  guard let data,
                        let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                        json["proof"] as? String == expected,
                        json["launch_nonce"] as? String == app.launchNonce else { return false }
                  return true
                }()
                step("readiness_live_proof", ok: proofOk, status: okCode)
                if !proofOk {
                  report.hijacked_studio_proof_rejected = false
                }
                completion()
              }
            }
          }
        }
      }
    }
  }

  private func runMainWorkflow(app: AppDelegate) {
    let hydrationJs = """
    (async () => {
      try { localStorage.setItem('vinci-onboard', 'done'); } catch (e) {}
      const sleep = (ms) => new Promise(r => setTimeout(r, ms));
      let hydrated = false;
      let hasNext = false;
      let hasCss = false;
      let color = '';
      for (let i = 0; i < 80; i++) {
        const root = document.querySelector('[data-testid="vinci-studio-root"]');
        hasNext = !!document.querySelector('script[src*="/_next/static/"]');
        hasCss = !!document.querySelector('link[href*="/_next/static/"]');
        const style = root ? getComputedStyle(root) : null;
        color = style ? style.color : '';
        if (root && hasNext && hasCss && color.length > 0) {
          hydrated = true;
          break;
        }
        await sleep(250);
      }
      return { hydrated, hasNext, hasCss, color };
    })()
    """
    wkEval(app: app, js: hydrationJs) { raw in
      if let data = raw.data(using: .utf8),
         let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
        report.studio_hydrated_ui_ok = dict["hydrated"] as? Bool ?? false
        step("studio_hydrated_ui", ok: report.studio_hydrated_ui_ok, detail: raw)
      } else {
        step("studio_hydrated_ui", ok: false, detail: "hydration eval failed")
      }

      DispatchQueue.main.async {
        app.webView.takeSnapshot(with: nil) { image, _ in
          if let image, let tiff = image.tiffRepresentation,
             let rep = NSBitmapImageRep(data: tiff),
             let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: self.screenshotPath))
          }
          self.smokeQueue.async {
            self.runSecurityChecks(app: app) {
              self.runWkWorkflow(app: app)
            }
          }
        }
      }
    }
  }

  private func runWkWorkflow(app: AppDelegate) {
    wkFetch(app: app, path: "/init", method: "POST", bodyJson: "{\"demo\":true}") { _ in
      wkFetch(
        app: app, path: "/runs", method: "POST",
        bodyJson: "{\"skill\":\"@tryvinci/image-generate\",\"inputs\":{\"prompt\":\"smoke cube\"}}"
      ) { raw in
        let img = self.parseStatus(raw)
        report.wk_proxy_mock_image_ok = img.0 == 200
        step("wk_proxy_mock_image", ok: report.wk_proxy_mock_image_ok, status: img.0)
        var imageAsset = ""
        if let data = img.1.data(using: .utf8),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let outputs = json["outputs"] as? [String], let first = outputs.first {
          imageAsset = first
        }

        wkFetch(
          app: app, path: "/runs", method: "POST",
          bodyJson: "{\"skill\":\"@tryvinci/video-generate\",\"inputs\":{\"prompt\":\"smoke clip\"}}"
        ) { raw2 in
          let vid = self.parseStatus(raw2)
          report.wk_proxy_mock_video_ok = vid.0 == 200
          step("wk_proxy_mock_video", ok: report.wk_proxy_mock_video_ok, status: vid.0)
          var jobId = ""
          var videoAsset = ""
          if let data = vid.1.data(using: .utf8),
             let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            jobId = (json["job_ids"] as? [String])?.first ?? ""
            videoAsset = (json["outputs"] as? [String])?.first ?? ""
          }
          self.pendingJobId = jobId
          self.continueAfterRuns(app: app, imageAsset: imageAsset, jobId: jobId, videoAsset: videoAsset)
        }
      }
    }
  }

  private func continueAfterRuns(app: AppDelegate, imageAsset: String, jobId: String, videoAsset: String) {
    if jobId.isEmpty {
      step("wk_proxy_receipt", ok: false, detail: "missing job id")
      afterReceipt(app: app, imageAsset: imageAsset, videoAsset: videoAsset)
      return
    }
    wkFetch(app: app, path: "/receipts/\(jobId)") { raw in
      let receipt = self.parseStatus(raw)
      report.wk_proxy_receipt_ok = receipt.0 == 200
      step("wk_proxy_receipt", ok: report.wk_proxy_receipt_ok, status: receipt.0)
      self.afterReceipt(app: app, imageAsset: imageAsset, videoAsset: videoAsset)
    }
  }

  private func afterReceipt(app: AppDelegate, imageAsset: String, videoAsset: String) {
    if imageAsset.isEmpty {
      step("wk_proxy_range_206", ok: false, detail: "no image asset")
      afterRange(app: app, imageAsset: imageAsset, videoAsset: videoAsset)
      return
    }
    let rangeJs = """
    (async () => {
      const res = await fetch('/vinci-api/assets/\(imageAsset)/file', {
        credentials: 'include',
        headers: { Range: 'bytes=0-3' }
      });
      return res.status;
    })()
    """
    wkEval(app: app, js: rangeJs) { raw in
      var code = Int(raw) ?? 0
      if code == 0, let data = raw.data(using: .utf8),
         let n = try? JSONSerialization.jsonObject(with: data) as? Int {
        code = n
      }
      report.wk_proxy_range_206_ok = code == 206
      step("wk_proxy_range_206", ok: report.wk_proxy_range_206_ok, status: code)
      self.afterRange(app: app, imageAsset: imageAsset, videoAsset: videoAsset)
    }
  }

  private func afterRange(app: AppDelegate, imageAsset: String, videoAsset: String) {
    if videoAsset.isEmpty {
      step("avfoundation_mp4_decode", ok: false, detail: "no video asset")
      step("wk_video_playback", ok: false, detail: "no video asset")
      afterVideo(app: app, imageAsset: imageAsset)
      return
    }
    avDecode(app: app, assetId: videoAsset) { ok in
      report.avfoundation_mp4_decode_ok = ok
      step("avfoundation_mp4_decode", ok: ok)
      wkVideoPlayback(app: app, assetId: videoAsset) { playOk in
        report.wk_video_playback_ok = playOk
        step("wk_video_playback", ok: playOk)
        self.afterVideo(app: app, imageAsset: imageAsset)
      }
    }
  }

  private func afterVideo(app: AppDelegate, imageAsset: String) {
    if imageAsset.isEmpty {
      step("wk_download_export_hash", ok: false, detail: "no image asset")
      afterExport(app: app, imageAsset: imageAsset)
      return
    }
    uiExportLastOutput(app: app, imageAsset: imageAsset) { exportOk, fileHash, assetHash in
      report.export_file_sha256 = fileHash
      report.wk_download_export_ok = exportOk && fileHash == assetHash && !fileHash.isEmpty
      step("wk_download_export_hash", ok: report.wk_download_export_ok)
      self.afterExport(app: app, imageAsset: imageAsset)
    }
  }

  private func afterExport(app: AppDelegate, imageAsset: String) {
    writeRelaunchState(app: app, imageAsset: imageAsset, jobId: pendingJobId)
    checkForeignDaemon(app: app) { isolated in
      report.foreign_daemon_isolated_ok = isolated
      step("foreign_daemon_isolated", ok: isolated)
      report.token_in_logs = logsContainSecret(app: app)
      step("token_not_in_logs", ok: !report.token_in_logs)
      spawnRelaunchVerify(app: app)
    }
  }

  private func uiExportLastOutput(
    app: AppDelegate,
    imageAsset: String,
    completion: @escaping (Bool, String, String) -> Void
  ) {
    app.smokeExportDownloadDone = false
    app.smokeExportByteCount = 0
    let exportPath = downloadPath ?? (app.dataHome + "/smoke-export.bin")
    let js = """
    (async () => {
      try { localStorage.setItem('vinci-onboard', 'done'); } catch (e) {}
      const sleep = (ms) => new Promise(r => setTimeout(r, ms));
      const runBtn = document.querySelector('button.run');
      if (runBtn && !runBtn.disabled) runBtn.click();
      for (let i = 0; i < 120; i++) {
        const link = document.querySelector('[data-testid="studio-export-last"]');
        if (link && link.getAttribute('href')) {
          link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
          return { clicked: true };
        }
        await sleep(500);
      }
      return { clicked: false };
    })()
    """
    wkEval(app: app, js: js) { _ in
      self.waitForExportFile(app: app, path: exportPath, assetId: imageAsset, attempt: 0, completion: completion)
    }
  }

  private func waitForExportFile(
    app: AppDelegate,
    path: String,
    assetId: String,
    attempt: Int,
    completion: @escaping (Bool, String, String) -> Void
  ) {
    if attempt >= 60 {
      completion(false, "", "")
      return
    }
    if app.smokeExportDownloadDone || FileManager.default.fileExists(atPath: path) {
      guard let fileData = try? Data(contentsOf: URL(fileURLWithPath: path)), !fileData.isEmpty else {
        smokeQueue.asyncAfter(deadline: .now() + 0.25) {
          self.waitForExportFile(app: app, path: path, assetId: assetId, attempt: attempt + 1, completion: completion)
        }
        return
      }
      let fileHash = SHA256.hash(data: fileData).map { String(format: "%02x", $0) }.joined()
      fetchAssetHash(app: app, assetId: assetId) { assetHash in
        completion(true, fileHash, assetHash)
      }
      return
    }
    smokeQueue.asyncAfter(deadline: .now() + 0.25) {
      self.waitForExportFile(app: app, path: path, assetId: assetId, attempt: attempt + 1, completion: completion)
    }
  }

  private func fetchAssetHash(app: AppDelegate, assetId: String, completion: @escaping (String) -> Void) {
    let js = """
    (async () => {
      const res = await fetch('/vinci-api/assets/\(assetId)/file', { credentials: 'include' });
      const buf = await res.arrayBuffer();
      const hash = await crypto.subtle.digest('SHA-256', buf);
      return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2,'0')).join('');
    })()
    """
    wkEval(app: app, js: js) { raw in
      completion(raw.trimmingCharacters(in: CharacterSet(charactersIn: "\"")))
    }
  }

  private func avDecode(app: AppDelegate, assetId: String, completion: @escaping (Bool) -> Void) {
    let tmp = NSTemporaryDirectory() + "smoke-video.mp4"
    fetchAssetToFile(app: app, assetId: assetId, destPath: tmp) { ok in
      guard ok else {
        completion(false)
        return
      }
      let asset = AVURLAsset(url: URL(fileURLWithPath: tmp))
      guard let track = asset.tracks(withMediaType: .video).first else {
        completion(false)
        return
      }
      completion(track.timeRange.duration.seconds > 0.1)
    }
  }

  private func fetchAssetToFile(
    app: AppDelegate,
    assetId: String,
    destPath: String,
    completion: @escaping (Bool) -> Void
  ) {
    let js = """
    (async () => {
      const res = await fetch('/vinci-api/assets/\(assetId)/file', { credentials: 'include' });
      if (!res.ok) return { status: res.status };
      const buf = await res.arrayBuffer();
      const bytes = new Uint8Array(buf);
      const chunk = 0x4000;
      const parts = [];
      for (let i = 0; i < bytes.length; i += chunk) {
        const slice = bytes.subarray(i, i + chunk);
        let bin = '';
        for (let j = 0; j < slice.length; j++) bin += String.fromCharCode(slice[j]);
        parts.push(btoa(bin));
      }
      return { status: res.status, parts };
    })()
    """
    wkEval(app: app, js: js) { raw in
      guard let data = raw.data(using: .utf8),
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            json["status"] as? Int == 200,
            let parts = json["parts"] as? [String] else {
        completion(false)
        return
      }
      var fileData = Data()
      for part in parts {
        guard let chunk = Data(base64Encoded: part) else {
          completion(false)
          return
        }
        fileData.append(chunk)
      }
      try? fileData.write(to: URL(fileURLWithPath: destPath))
      completion(!fileData.isEmpty)
    }
  }

  private func wkVideoPlayback(app: AppDelegate, assetId: String, completion: @escaping (Bool) -> Void) {
    let js = """
    (async () => {
      const v = document.createElement('video');
      v.src = '/vinci-api/assets/\(assetId)/file';
      v.muted = true;
      document.body.appendChild(v);
      await new Promise((resolve, reject) => {
        v.onloadeddata = () => resolve(true);
        v.onerror = () => reject('error');
        setTimeout(() => reject('timeout'), 15000);
      });
      await v.play();
      await new Promise(r => setTimeout(r, 400));
      return { width: v.videoWidth, time: v.currentTime };
    })()
    """
    wkEval(app: app, js: js) { raw in
      guard let data = raw.data(using: .utf8),
            let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let width = dict["width"] as? Int, width > 0,
            let time = dict["time"] as? Double, time > 0 else {
        completion(false)
        return
      }
      completion(true)
    }
  }

  private func writeRelaunchState(app: AppDelegate, imageAsset: String, jobId: String) {
    guard let statePath else { return }
    let payload: [String: String] = ["job_id": jobId, "image_asset": imageAsset]
    if let data = try? JSONSerialization.data(withJSONObject: payload) {
      try? data.write(to: URL(fileURLWithPath: statePath))
    }
  }

  private func spawnRelaunchVerify(app: AppDelegate) {
    guard let statePath, FileManager.default.fileExists(atPath: statePath),
          let relaunch = relaunchReportPath,
          let exe = Bundle.main.executableURL else {
      report.app_relaunch_persistence_ok = false
      step("app_relaunch_persistence", ok: false, detail: "no relaunch config")
      finishCleanup(app: app)
      return
    }
    writeReportSnapshot()
    app.releaseInstanceLock()
    app.stopServices()
    smokeQueue.asyncAfter(deadline: .now() + 2.0) {
      let proc = Process()
      proc.executableURL = exe
      proc.arguments = [
        "--smoke-relaunch-verify",
        "--smoke-report", relaunch,
        "--smoke-home", app.dataHome,
        "--smoke-state", statePath,
      ]
      var env = ProcessInfo.processInfo.environment
      env["VINCI_SMOKE_RELAY"] = "1"
      proc.environment = env
      do {
        try proc.run()
        proc.waitUntilExit()
        report.app_relaunch_persistence_ok = proc.terminationStatus == 0
          && FileManager.default.fileExists(atPath: relaunch)
      } catch {
        report.app_relaunch_persistence_ok = false
      }
      step("app_relaunch_persistence", ok: report.app_relaunch_persistence_ok)
      finishCleanup(app: app)
    }
  }

  private func runRelaunchVerify(app: AppDelegate) {
    guard let statePath,
          let data = try? Data(contentsOf: URL(fileURLWithPath: statePath)),
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
          let jobId = json["job_id"], let asset = json["image_asset"] else {
      finish(ok: false, detail: "missing relaunch state")
      return
    }
    wkFetch(app: app, path: "/receipts/\(jobId)") { raw in
      let receipt = self.parseStatus(raw)
      step("relaunch_receipt", ok: receipt.0 == 200, status: receipt.0)
      wkFetch(app: app, path: "/assets/\(asset)/file") { raw2 in
        let assetOk = self.parseStatus(raw2).0 == 200
        step("relaunch_asset", ok: assetOk)
        report.app_relaunch_persistence_ok = receipt.0 == 200 && assetOk
        finish(ok: report.app_relaunch_persistence_ok, detail: report.app_relaunch_persistence_ok ? "relaunch ok" : "relaunch failed")
      }
    }
  }

  private func checkForeignDaemon(app: AppDelegate, completion: @escaping (Bool) -> Void) {
    let foreignHome = app.dataHome + "/foreign-smoke"
    try? FileManager.default.createDirectory(atPath: foreignHome, withIntermediateDirectories: true)
    let python = app.bundleResourcePath("runtime/bin/python3")
    let proc = ChildProcess(
      executable: python,
      args: [
        "-m", "vinci_daemon.app",
        "--host", "127.0.0.1", "--port", "0", "--desktop",
        "--launch-nonce", "foreign-smoke-nonce",
      ],
      env: [
        "HOME": NSHomeDirectory(),
        "VINCI_HOME": foreignHome,
        "VINCI_BRIDGE_TOKEN": "foreign-token",
        "VINCI_ALLOW_LIVE_SPEND": "0",
      ],
      logPath: NSTemporaryDirectory() + "foreign-daemon.log"
    )
    do {
      try proc.start()
      guard let ready = proc.readReadyLine(timeout: 15) else {
        completion(false)
        return
      }
      let parts = ready.split(separator: " ")
      let foreignPort = Int(parts[1]) ?? 0
      let foreignNonce = parts.count > 2 ? String(parts[2]) : ""
      httpStatus(url: "http://127.0.0.1:\(foreignPort)/healthz") { code, data in
        var foreignOk = false
        if code == 200, let data,
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           json["launch_nonce"] as? String == "foreign-smoke-nonce" {
          foreignOk = true
        }
        httpStatus(url: "http://127.0.0.1:\(app.daemonPort)/healthz") { appCode, appData in
          var appOk = false
          if appCode == 200, let appData,
             let json = try? JSONSerialization.jsonObject(with: appData) as? [String: Any],
             json["launch_nonce"] as? String == app.launchNonce {
            appOk = true
          }
          proc.terminateAndWait()
          let isolated = foreignPort > 0
            && foreignPort != app.daemonPort
            && foreignNonce == "foreign-smoke-nonce"
            && foreignOk
            && appOk
          completion(isolated)
        }
      }
    } catch {
      completion(false)
    }
  }

  private func finishCleanup(app: AppDelegate) {
    let daemon = app.daemon
    let studio = app.studio
    let tracked = Set((daemon?.descendantPids() ?? []) + (studio?.descendantPids() ?? []) + [daemon?.pid ?? 0, studio?.pid ?? 0])
    app.stopServices()
    smokeQueue.asyncAfter(deadline: .now() + 2.0) {
      var alive = false
      for pid in tracked where pid > 0 {
        if kill(pid, 0) == 0 {
          alive = true
          break
        }
      }
      report.quit_descendants_clean_ok = !alive
      step("quit_descendants_clean", ok: report.quit_descendants_clean_ok)
      finish(ok: allChecksPass(), detail: allChecksPass() ? "smoke passed" : "failed")
    }
  }

  private func allChecksPass() -> Bool {
    report.studio_readiness_hmac_ok && report.studio_hydrated_ui_ok
      && report.proxy_unauth_denied && report.proxy_cross_origin_denied && report.proxy_wrong_host_denied
      && report.readiness_no_bridge_denied && report.readiness_wrong_bridge_denied && report.hijacked_studio_proof_rejected
      && report.wk_proxy_mock_image_ok && report.wk_proxy_mock_video_ok
      && report.avfoundation_mp4_decode_ok && report.wk_video_playback_ok && report.wk_proxy_receipt_ok
      && report.wk_proxy_range_206_ok && report.wk_download_export_ok && report.app_relaunch_persistence_ok
      && report.foreign_daemon_isolated_ok && !report.token_in_logs && report.quit_descendants_clean_ok
      && !report.app_bundle_sha256.isEmpty
  }

  private func logsContainSecret(app: AppDelegate) -> Bool {
    let logs = NSHomeDirectory() + "/Library/Logs/Vinci"
    for name in ["daemon.log", "studio.log"] {
      guard let text = try? String(contentsOfFile: logs + "/" + name, encoding: .utf8) else { continue }
      if text.contains(app.bridgeToken) || text.contains(app.studioSession) { return true }
    }
    return false
  }

  private func writeReportSnapshot() {
    let url = URL(fileURLWithPath: reportPath)
    if let data = try? JSONEncoder().encode(report) {
      try? data.write(to: url)
    }
  }

  private func finish(ok: Bool, detail: String) {
    finishLock.lock()
    guard !finished else {
      finishLock.unlock()
      return
    }
    finished = true
    finishLock.unlock()
    watchdog?.cancel()
    watchdog = nil
    delegate?.stopServices()
    report.finished_at = isoNow()
    step("finish", ok: ok, detail: detail)
    let url = URL(fileURLWithPath: reportPath)
    do {
      let enc = JSONEncoder()
      enc.outputFormatting = [.sortedKeys]
      try enc.encode(report).write(to: url)
    } catch {
      fputs("smoke report write failed\n", stderr)
      exit(2)
    }
    DispatchQueue.main.async {
      NSApp.terminate(nil)
    }
    exit(ok ? 0 : 1)
  }
}
