package __PACKAGE_NAME__.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.RemoteViews
import __PACKAGE_NAME__.R
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import org.json.JSONObject

private const val SNAPSHOT_FILENAME = "localflight-widget-snapshot.json"
private const val SNAPSHOT_SCHEMA_VERSION = 1
private const val MAX_SNAPSHOT_BYTES = 64 * 1024

private data class WidgetRow(
  val flight: String,
  val time: String,
  val route: String,
  val status: String,
  val pinned: Boolean
)

private data class WidgetData(
  val airport: String,
  val direction: String,
  val source: String,
  val stale: Boolean,
  val rows: List<WidgetRow>
)

class LocalFlightWidgetProvider : AppWidgetProvider() {
  override fun onUpdate(
    context: Context,
    appWidgetManager: AppWidgetManager,
    appWidgetIds: IntArray
  ) {
    appWidgetIds.forEach { render(context, appWidgetManager, it) }
  }

  override fun onAppWidgetOptionsChanged(
    context: Context,
    appWidgetManager: AppWidgetManager,
    appWidgetId: Int,
    newOptions: Bundle
  ) {
    render(context, appWidgetManager, appWidgetId)
  }

  private fun render(context: Context, manager: AppWidgetManager, appWidgetId: Int) {
    val views = RemoteViews(context.packageName, R.layout.localflight_widget)
    val data = readSnapshot(context)
    val minWidth = manager.getAppWidgetOptions(appWidgetId)
      .getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 180)
    val rowLimit = if (minWidth >= 300) 3 else 1
    val rows = data?.rows.orEmpty().take(rowLimit)

    views.setTextViewText(R.id.widget_airport, data?.let { "${it.airport} · ${it.direction}" } ?: "LOCAL FLIGHT")
    views.setTextViewText(
      R.id.widget_freshness,
      when {
        data == null -> "OPEN APP"
        data.stale -> "STALE · ${data.source}"
        else -> data.source
      }
    )
    views.setTextColor(
      R.id.widget_freshness,
      context.getColor(if (data?.stale == true) R.color.localflight_widget_amber else R.color.localflight_widget_green)
    )

    val rowIds = intArrayOf(R.id.widget_row_1, R.id.widget_row_2, R.id.widget_row_3)
    rowIds.forEachIndexed { index, viewId ->
      val row = rows.getOrNull(index)
      views.setViewVisibility(viewId, if (row == null) View.GONE else View.VISIBLE)
      if (row != null) {
        val pin = if (row.pinned) "● " else ""
        views.setTextViewText(viewId, "$pin${row.time}  ${row.flight}  ${row.route}  ${row.status}")
      }
    }
    views.setViewVisibility(R.id.widget_empty, if (rows.isEmpty()) View.VISIBLE else View.GONE)
    views.setTextViewText(
      R.id.widget_empty,
      if (data == null) "Open Local Flight to prepare the board" else "Waiting for board rows"
    )
    views.setContentDescription(
      R.id.widget_root,
      data?.let { "Local Flight ${it.airport} ${it.direction} widget" } ?: "Open Local Flight"
    )

    context.packageManager.getLaunchIntentForPackage(context.packageName)?.let { launchIntent ->
      launchIntent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
      views.setOnClickPendingIntent(
        R.id.widget_root,
        PendingIntent.getActivity(
          context,
          appWidgetId,
          launchIntent,
          PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
      )
    }

    val refreshIntent = Intent(Intent.ACTION_VIEW, Uri.parse("localflight://widgets?refresh=1"))
      .setPackage(context.packageName)
      .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
    views.setOnClickPendingIntent(
      R.id.widget_refresh,
      PendingIntent.getActivity(
        context,
        appWidgetId,
        refreshIntent,
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
      )
    )
    manager.updateAppWidget(appWidgetId, views)
  }

  private fun readSnapshot(context: Context): WidgetData? {
    val file = File(context.filesDir, SNAPSHOT_FILENAME)
    if (!file.isFile || file.length() !in 1..MAX_SNAPSHOT_BYTES.toLong()) return null

    return try {
      val root = JSONObject(file.readText(Charsets.UTF_8))
      if (root.optInt("schemaVersion", -1) != SNAPSHOT_SCHEMA_VERSION) return null
      val airport = root.optJSONObject("airport") ?: return null
      val source = root.optJSONObject("source")
      val medium = root.optJSONObject("medium")
      val rowsJson = medium?.optJSONArray("rows")
      val rows = buildList {
        if (rowsJson != null) {
          for (index in 0 until minOf(rowsJson.length(), 4)) {
            val row = rowsJson.optJSONObject(index) ?: continue
            val flight = clean(row.optString("flightDisplay"), 24)
            if (flight.isEmpty()) continue
            add(
              WidgetRow(
                flight = flight,
                time = clean(row.optString("displayTime"), 12, "--:--"),
                route = clean(row.optString("routeCode"), 8).ifEmpty {
                  clean(row.optString("routeName"), 24, "-")
                },
                status = clean(row.optString("statusDisplay"), 20, "SCHEDULE"),
                pinned = row.optBoolean("pinned", false)
              )
            )
          }
        }
      }
      WidgetData(
        airport = clean(airport.optString("code"), 8, "---"),
        direction = if (airport.optString("view") == "arrivals") "ARR" else "DEP",
        source = clean(source?.optString("lastUpdatedLabel"), 32, "Waiting").uppercase(),
        stale = root.optBoolean("stale", false) || isExpired(root.optString("expiresAt")),
        rows = rows
      )
    } catch (_: Exception) {
      null
    }
  }

  private fun clean(value: String?, limit: Int, fallback: String = ""): String {
    val trimmed = value.orEmpty().trim().takeUnless { it == "-" }.orEmpty()
    return (trimmed.ifEmpty { fallback }).take(limit)
  }

  private fun isExpired(value: String): Boolean {
    if (value.isBlank()) return true
    for (pattern in listOf("yyyy-MM-dd'T'HH:mm:ss.SSSX", "yyyy-MM-dd'T'HH:mm:ssX")) {
      try {
        val parser = SimpleDateFormat(pattern, Locale.US).apply {
          isLenient = false
          timeZone = TimeZone.getTimeZone("UTC")
        }
        val parsed = parser.parse(value) ?: continue
        return parsed.time <= System.currentTimeMillis()
      } catch (_: Exception) {
        // Try the next supported ISO-8601 shape.
      }
    }
    return true
  }
}
