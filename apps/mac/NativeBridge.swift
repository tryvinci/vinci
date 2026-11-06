import AppKit
import Photos
import WebKit

/// Handles `window.webkit.messageHandlers.vinciNative` from Studio.
final class VinciNativeBridge: NSObject, WKScriptMessageHandler {
  func userContentController(
    _ userContentController: WKUserContentController,
    didReceive message: WKScriptMessage
  ) {
    guard message.name == "vinciNative",
          let body = message.body as? [String: Any],
          let action = body["action"] as? String else { return }
    switch action {
    case "revealInFinder":
      let path = body["path"] as? String ?? ""
      revealInFinder(path: path)
    case "importToPhotos":
      let path = body["path"] as? String ?? ""
      let album = body["album"] as? String ?? "Vinci"
      importToPhotos(path: path, albumName: album)
    default:
      break
    }
  }

  func revealInFinder(path: String) {
    guard !path.isEmpty else { return }
    let url = URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    NSWorkspace.shared.activateFileViewerSelecting([url])
  }

  func importToPhotos(path: String, albumName: String) {
    guard !path.isEmpty else { return }
    let url = URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
    guard FileManager.default.fileExists(atPath: url.path) else { return }
    let ext = url.pathExtension.lowercased()
    let isVideo = ext == "mp4" || ext == "mov" || ext == "m4v"
    PHPhotoLibrary.requestAuthorization(for: .addOnly) { status in
      guard status == .authorized || status == .limited else { return }
      PHPhotoLibrary.shared().performChanges({
        let placeholder: PHObjectPlaceholder?
        if isVideo {
          placeholder = PHAssetCreationRequest.creationRequestForAssetFromVideo(atFileURL: url)?
            .placeholderForCreatedAsset
        } else {
          placeholder = PHAssetCreationRequest.creationRequestForAssetFromImage(atFileURL: url)?
            .placeholderForCreatedAsset
        }
        guard let placeholder else { return }
        let title = albumName.trimmingCharacters(in: .whitespacesAndNewlines)
        let albumTitle = title.isEmpty ? "Vinci" : title
        let fetch = PHAssetCollection.fetchAssetCollections(
          with: .album,
          subtype: .albumRegular,
          options: {
            let opts = PHFetchOptions()
            opts.predicate = NSPredicate(format: "title = %@", albumTitle)
            return opts
          }()
        )
        if let collection = fetch.firstObject {
          let change = PHAssetCollectionChangeRequest(for: collection)
          change?.addAssets([placeholder] as NSArray)
        } else {
          let create = PHAssetCollectionChangeRequest.creationRequestForAssetCollection(withTitle: albumTitle)
          create.addAssets([placeholder] as NSArray)
        }
      })
    }
  }
}
