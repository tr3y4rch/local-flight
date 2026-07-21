package cc.beacontools.localflight.widgetbridge

import android.content.Context
import android.view.KeyEvent
import android.view.ViewGroup
import expo.modules.kotlin.AppContext
import expo.modules.kotlin.viewevent.EventDispatcher
import expo.modules.kotlin.views.ExpoView

/**
 * Transparent React host for Local Flight's hardware-keyboard shortcuts.
 * dispatchKeyEvent observes keys before a focused React descendant consumes
 * them, while all unrelated input continues through the normal event chain.
 */
class LocalFlightShortcutView(
  context: Context,
  appContext: AppContext
) : ExpoView(context, appContext) {
  private val onShortcut by EventDispatcher<Map<String, Any>>()

  init {
    orientation = VERTICAL
    isFocusable = true
    isFocusableInTouchMode = true
    descendantFocusability = ViewGroup.FOCUS_AFTER_DESCENDANTS
  }

  override fun onAttachedToWindow() {
    super.onAttachedToWindow()
    post {
      if (findFocus() == null) {
        requestFocus()
      }
    }
  }

  override fun dispatchKeyEvent(event: KeyEvent): Boolean {
    if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) {
      val key = shortcutKey(event)
      if (key != null) {
        onShortcut(mapOf("key" to key))
        return true
      }
    }
    return super.dispatchKeyEvent(event)
  }

  private fun shortcutKey(event: KeyEvent): String? {
    if (event.keyCode == KeyEvent.KEYCODE_ESCAPE) {
      return "escape"
    }
    if (!event.isCtrlPressed && !event.isMetaPressed) {
      return null
    }
    return when (event.keyCode) {
      KeyEvent.KEYCODE_1 -> "1"
      KeyEvent.KEYCODE_2 -> "2"
      KeyEvent.KEYCODE_3 -> "3"
      KeyEvent.KEYCODE_4 -> "4"
      KeyEvent.KEYCODE_R -> "r"
      KeyEvent.KEYCODE_F -> "f"
      else -> null
    }
  }
}
