package ai.tryvinci.studio

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.app.Activity

class MainActivity : Activity() {
    private lateinit var webView: WebView
    private lateinit var urlBar: EditText

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("vinci", MODE_PRIVATE)
        val initial = prefs.getString("daemon", DEFAULT_URL) ?: DEFAULT_URL

        urlBar = EditText(this).apply {
            setText(initial)
            hint = "Studio URL (:4311 TypeScript, /studio HTML)"
        }
        val load = Button(this).apply { text = "Load" }
        webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.cacheMode = WebSettings.LOAD_DEFAULT
            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun onReceivedError(
                    view: WebView,
                    request: WebResourceRequest,
                    error: WebResourceError,
                ) {
                    if (request.isForMainFrame) showOffline()
                }
            }
        }
        load.setOnClickListener {
            val url = urlBar.text.toString().trim()
            prefs.edit().putString("daemon", url).apply()
            webView.loadUrl(url)
        }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(urlBar, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(load)
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(bar)
            addView(
                webView,
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f),
            )
        }
        setContentView(root)
        webView.loadUrl(initial)
    }

    private fun showOffline() {
        webView.loadDataWithBaseURL(
            null,
            """
            <html><body style="font-family:sans-serif;background:#12100e;color:#f3ece0;padding:1.5rem">
            <h1>Start the Vinci daemon</h1>
            <p>This app is a WebView of TypeScript Studio (<code>:4311</code>). HTML <code>/studio</code> is the fallback. Keys stay on the daemon host.</p>
            <pre>./scripts/vinci studio --lan</pre>
            <p>Emulator: <code>http://10.0.2.2:4311</code> or <code>http://10.0.2.2:4310/studio</code>. Device: the LAN URL printed by <code>--lan</code>.</p>
            </body></html>
            """.trimIndent(),
            "text/html",
            "utf-8",
            null,
        )
    }

    companion object {
        const val DEFAULT_URL = "http://10.0.2.2:4311"
    }
}
