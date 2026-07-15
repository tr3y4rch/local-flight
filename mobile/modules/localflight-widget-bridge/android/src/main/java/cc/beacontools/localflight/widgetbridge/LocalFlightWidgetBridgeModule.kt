package cc.beacontools.localflight.widgetbridge

import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class LocalFlightWidgetBridgeModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("LocalFlightWidgetBridge")

    AsyncFunction("reload") {
      val context = appContext.reactContext?.applicationContext
        ?: return@AsyncFunction mapOf("available" to false, "widgetCount" to 0)
      val provider = ComponentName(
        context.packageName,
        "${context.packageName}.widget.LocalFlightWidgetProvider"
      )
      val manager = AppWidgetManager.getInstance(context)
      val widgetIds = manager.getAppWidgetIds(provider)
      if (widgetIds.isNotEmpty()) {
        val intent = Intent(AppWidgetManager.ACTION_APPWIDGET_UPDATE)
          .setComponent(provider)
          .putExtra(AppWidgetManager.EXTRA_APPWIDGET_IDS, widgetIds)
        context.sendBroadcast(intent)
      }
      mapOf("available" to true, "widgetCount" to widgetIds.size)
    }
  }
}
