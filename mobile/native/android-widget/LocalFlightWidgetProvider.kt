package __PACKAGE_NAME__.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
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
  val routeName: String,
  val routeCode: String,
  val status: String,
  val statusTone: String,
  val gate: String,
  val terminal: String,
  val pinned: Boolean
)

private data class WidgetData(
  val airport: String,
  val airportName: String,
  val direction: String,
  val source: String,
  val stale: Boolean,
  val showGateTerminal: Boolean,
  val appearance: String,
  val pinnedFlight: WidgetRow?,
  val rows: List<WidgetRow>
)

private data class WidgetPalette(
  val text: Int,
  val muted: Int,
  val sky: Int,
  val sea: Int,
  val amber: Int,
  val red: Int,
  val backgroundDrawable: Int,
  val rowDrawable: Int
)

private data class BoardRowViews(
  val container: Int,
  val accent: Int,
  val time: Int,
  val flight: Int,
  val route: Int,
  val status: Int,
  val info: Int
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
    val options = manager.getAppWidgetOptions(appWidgetId)
    val minWidth = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 180)
    val minHeight = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 110)
    val compact = minWidth < 240 || minHeight < 135
    val palette = resolvePalette(context, data?.appearance ?: "system")

    views.setInt(R.id.widget_root, "setBackgroundResource", palette.backgroundDrawable)
    views.setViewVisibility(R.id.widget_compact, if (compact) View.VISIBLE else View.GONE)
    views.setViewVisibility(R.id.widget_board, if (compact) View.GONE else View.VISIBLE)
    renderCompact(context, views, data, minHeight, palette)
    renderBoard(context, views, data, minHeight, palette)

    views.setContentDescription(
      R.id.widget_root,
      widgetDescription(context, data)
    )
    bindActions(context, views, appWidgetId)
    manager.updateAppWidget(appWidgetId, views)
  }

  private fun renderCompact(
    context: Context,
    views: RemoteViews,
    data: WidgetData?,
    minHeight: Int,
    palette: WidgetPalette
  ) {
    val flight = data?.pinnedFlight ?: data?.rows?.firstOrNull()
    val short = minHeight < 150
    val tiny = minHeight < 120
    views.setViewVisibility(R.id.widget_compact_label_row, if (tiny) View.GONE else View.VISIBLE)
    views.setViewVisibility(R.id.widget_compact_route, if (short) View.GONE else View.VISIBLE)
    views.setViewVisibility(R.id.widget_compact_footer, if (short) View.GONE else View.VISIBLE)
    views.setTextViewText(
      R.id.widget_compact_airport,
      data?.let { "${it.airport}  ·  ${it.direction}" } ?: context.getString(R.string.localflight_widget_name).uppercase()
    )
    views.setTextViewText(
      R.id.widget_compact_freshness,
      when {
        data == null -> context.getString(R.string.localflight_widget_open_app).uppercase()
        data.stale -> context.getString(R.string.localflight_widget_update_needed)
        else -> data.source
      }
    )
    views.setTextColor(
      R.id.widget_compact_freshness,
      if (data?.stale == true) palette.amber else palette.sea
    )
    views.setTextViewText(
      R.id.widget_compact_label,
      context.getString(
        if (data?.pinnedFlight != null) R.string.localflight_widget_pinned_flight else R.string.localflight_widget_next_flight
      ).uppercase()
    )
    views.setTextViewText(R.id.widget_compact_flight, flight?.flight ?: context.getString(R.string.localflight_widget_pin_flight))
    views.setTextViewText(
      R.id.widget_compact_route,
      flight?.routeName ?: context.getString(R.string.localflight_widget_choose_flight)
    )
    views.setTextViewText(
      R.id.widget_compact_meta,
      flight?.let {
        listOf(it.time, it.routeCode).filter(String::isNotEmpty).joinToString("  ·  ")
      } ?: context.getString(R.string.localflight_widget_snapshot_prepared)
    )
    views.setTextViewText(
      R.id.widget_compact_status,
      when {
        flight == null -> context.getString(R.string.localflight_widget_waiting).uppercase()
        else -> flight.status
      }
    )
    views.setTextColor(
      R.id.widget_compact_status,
      statusColor(palette, flight?.statusTone)
    )
    for (viewId in listOf(R.id.widget_compact_airport, R.id.widget_compact_label, R.id.widget_compact_meta)) {
      views.setTextColor(viewId, palette.muted)
    }
    views.setTextColor(R.id.widget_compact_flight, palette.text)
    views.setTextColor(R.id.widget_compact_route, palette.text)
    val info = if (data?.showGateTerminal == true) flight?.gate.orEmpty().ifEmpty { flight?.terminal.orEmpty() } else ""
    views.setViewVisibility(R.id.widget_compact_info, if (info.isEmpty()) View.GONE else View.VISIBLE)
    views.setTextViewText(R.id.widget_compact_info, info.uppercase())
    views.setTextColor(R.id.widget_compact_info, palette.text)
  }

  private fun renderBoard(
    context: Context,
    views: RemoteViews,
    data: WidgetData?,
    minHeight: Int,
    palette: WidgetPalette
  ) {
    views.setTextViewText(R.id.widget_board_airport, data?.airportName ?: context.getString(R.string.localflight_widget_name))
    views.setTextViewText(
      R.id.widget_board_direction,
      data?.let { "${it.airport}  ·  ${it.direction}" } ?: context.getString(R.string.localflight_widget_airport_board).uppercase()
    )
    views.setTextViewText(
      R.id.widget_board_freshness,
      when {
        data == null -> context.getString(R.string.localflight_widget_open_app).uppercase()
        data.stale -> "${context.getString(R.string.localflight_widget_update_needed)}  ·  ${data.source}"
        else -> data.source
      }
    )
    views.setTextColor(
      R.id.widget_board_freshness,
      if (data?.stale == true) palette.amber else palette.sea
    )
    views.setTextColor(R.id.widget_board_airport, palette.text)
    views.setTextColor(R.id.widget_board_direction, palette.sea)
    views.setTextColor(R.id.widget_empty, palette.muted)

    val rowLimit = when {
      minHeight < 170 -> 1
      minHeight < 215 -> 2
      else -> 3
    }
    val rows = data?.rows.orEmpty().take(rowLimit)
    val rowViews = listOf(
      BoardRowViews(R.id.widget_row_1, R.id.widget_row_1_accent, R.id.widget_row_1_time, R.id.widget_row_1_flight, R.id.widget_row_1_route, R.id.widget_row_1_status, R.id.widget_row_1_info),
      BoardRowViews(R.id.widget_row_2, R.id.widget_row_2_accent, R.id.widget_row_2_time, R.id.widget_row_2_flight, R.id.widget_row_2_route, R.id.widget_row_2_status, R.id.widget_row_2_info),
      BoardRowViews(R.id.widget_row_3, R.id.widget_row_3_accent, R.id.widget_row_3_time, R.id.widget_row_3_flight, R.id.widget_row_3_route, R.id.widget_row_3_status, R.id.widget_row_3_info)
    )
    rowViews.forEachIndexed { index, ids ->
      val row = rows.getOrNull(index)
      views.setViewVisibility(ids.container, if (row == null) View.GONE else View.VISIBLE)
      if (row != null) {
        val info = if (data?.showGateTerminal == true) row.gate.ifEmpty { row.terminal } else ""
        views.setInt(ids.container, "setBackgroundResource", palette.rowDrawable)
        views.setViewVisibility(ids.accent, if (row.pinned) View.VISIBLE else View.INVISIBLE)
        views.setTextViewText(ids.time, row.time)
        views.setTextViewText(ids.flight, row.flight)
        views.setTextViewText(ids.route, listOf(row.routeName, row.routeCode).filter(String::isNotEmpty).joinToString("  ·  "))
        views.setTextViewText(ids.status, row.status)
        views.setTextViewText(ids.info, if (info.isEmpty()) "" else if (row.gate.isNotEmpty()) "Gate $info" else "Terminal $info")
        views.setViewVisibility(ids.info, if (info.isEmpty()) View.GONE else View.VISIBLE)
        views.setTextColor(ids.time, palette.text)
        views.setTextColor(ids.flight, palette.sky)
        views.setTextColor(ids.route, palette.muted)
        views.setTextColor(ids.status, statusColor(palette, row.statusTone))
        views.setTextColor(ids.info, palette.muted)
        views.setInt(ids.accent, "setBackgroundColor", palette.amber)
      }
    }
    views.setViewVisibility(R.id.widget_empty, if (rows.isEmpty()) View.VISIBLE else View.GONE)
    views.setTextViewText(
      R.id.widget_empty,
      if (data == null) context.getString(R.string.localflight_widget_prepare_board) else context.getString(R.string.localflight_widget_waiting_board)
    )
  }

  private fun bindActions(context: Context, views: RemoteViews, appWidgetId: Int) {
    val boardIntent = Intent(Intent.ACTION_VIEW, Uri.parse("localflight://board?source=widget"))
      .setPackage(context.packageName)
      .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
    views.setOnClickPendingIntent(
      R.id.widget_root,
      PendingIntent.getActivity(
        context,
        appWidgetId,
        boardIntent,
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
      )
    )

    val refreshIntent = Intent(Intent.ACTION_VIEW, Uri.parse("localflight://board?source=widget&refresh=1"))
      .setPackage(context.packageName)
      .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
    val compactRefresh = PendingIntent.getActivity(
      context,
      appWidgetId * 2,
      refreshIntent,
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )
    val boardRefresh = PendingIntent.getActivity(
      context,
      appWidgetId * 2 + 1,
      refreshIntent,
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )
    views.setOnClickPendingIntent(R.id.widget_compact_refresh, compactRefresh)
    views.setOnClickPendingIntent(R.id.widget_board_refresh, boardRefresh)
    views.setViewVisibility(R.id.widget_compact_refresh, View.GONE)
    views.setViewVisibility(R.id.widget_board_refresh, View.GONE)
  }

  private fun widgetDescription(context: Context, data: WidgetData?): String {
    data ?: return context.getString(R.string.localflight_widget_prepare_widget)
    val flight = data.pinnedFlight ?: data.rows.firstOrNull()
    val state = when {
      data.stale -> context.getString(R.string.localflight_widget_update_needed).lowercase()
      flight != null -> flight.status.lowercase()
      else -> context.getString(R.string.localflight_widget_waiting_board).lowercase()
    }
    return listOfNotNull(
      "Local Flight ${data.airportName}",
      data.direction.lowercase(),
      flight?.flight,
      flight?.routeName,
      flight?.time,
      state
    ).filter(String::isNotEmpty).joinToString(", ")
  }

  private fun readSnapshot(context: Context): WidgetData? {
    val file = File(context.filesDir, SNAPSHOT_FILENAME)
    if (!file.isFile || file.length() !in 1..MAX_SNAPSHOT_BYTES.toLong()) return null

    return try {
      val root = JSONObject(file.readText(Charsets.UTF_8))
      if (root.optInt("schemaVersion", -1) != SNAPSHOT_SCHEMA_VERSION) return null
      val airport = root.optJSONObject("airport") ?: return null
      val source = root.optJSONObject("source")
      val preferences = root.optJSONObject("preferences")
      val small = root.optJSONObject("small")
      val pinnedFlight = if (small?.optString("source") == "pinned") {
        parseRow(small.optJSONObject("flight"), pinned = true)
      } else {
        null
      }
      val rowsJson = root.optJSONObject("medium")?.optJSONArray("rows")
      val rows = buildList {
        if (rowsJson != null) {
          for (index in 0 until minOf(rowsJson.length(), 4)) {
            parseRow(rowsJson.optJSONObject(index))?.let(::add)
          }
        }
      }
      WidgetData(
        airport = clean(airport.optString("code"), 8, "---"),
        airportName = clean(airport.optString("name"), 80, "Local Flight Airport"),
        direction = if (airport.optString("view") == "arrivals") "ARRIVALS" else "DEPARTURES",
        source = clean(source?.optString("lastUpdatedLabel"), 32, "Waiting").uppercase(),
        stale = root.optBoolean("stale", false) || isExpired(root.optString("expiresAt")),
        showGateTerminal = preferences?.optBoolean("showGateTerminal", true) != false,
        appearance = preferences?.optString("widgetAppearance")?.takeIf { it == "light" || it == "dark" } ?: "system",
        pinnedFlight = pinnedFlight,
        rows = rows
      )
    } catch (_: Exception) {
      null
    }
  }

  private fun parseRow(value: JSONObject?, pinned: Boolean? = null): WidgetRow? {
    value ?: return null
    val flight = clean(value.optString("flightDisplay"), 24)
    if (flight.isEmpty()) return null
    val tone = value.optString("statusTone").takeIf {
      it in setOf("scheduled", "departed", "boarding", "delayed", "cancelled")
    } ?: "scheduled"
    return WidgetRow(
      flight = flight,
      time = clean(value.optString("displayTime"), 12, "--:--").substringBefore(" "),
      routeName = clean(value.optString("routeName"), 64, "-"),
      routeCode = clean(value.optString("routeCode"), 8),
      status = clean(value.optString("statusDisplay"), 20, "SCHEDULE"),
      statusTone = tone,
      gate = clean(value.optString("gate"), 16),
      terminal = clean(value.optString("terminal"), 16),
      pinned = pinned ?: value.optBoolean("pinned", false)
    )
  }

  private fun statusColor(palette: WidgetPalette, tone: String?): Int {
    if (tone == "delayed") return palette.amber
    return when (tone) {
      "boarding", "departed" -> palette.sea
      "cancelled" -> palette.red
      else -> palette.sky
    }
  }

  private fun resolvePalette(context: Context, preference: String): WidgetPalette {
    val systemDark = (context.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
    val dark = preference == "dark" || (preference == "system" && systemDark)
    return if (dark) {
      WidgetPalette(
        text = Color.parseColor("#F5F0E8"), muted = Color.parseColor("#A4B3BE"),
        sky = Color.parseColor("#74B5DE"), sea = Color.parseColor("#59C1A5"),
        amber = Color.parseColor("#E4B454"), red = Color.parseColor("#F07C62"),
        backgroundDrawable = R.drawable.localflight_widget_background_dark,
        rowDrawable = R.drawable.localflight_widget_row_dark
      )
    } else {
      WidgetPalette(
        text = Color.parseColor("#132638"), muted = Color.parseColor("#536575"),
        sky = Color.parseColor("#2F6F9F"), sea = Color.parseColor("#1F6F61"),
        amber = Color.parseColor("#925D10"), red = Color.parseColor("#A74732"),
        backgroundDrawable = R.drawable.localflight_widget_background_light,
        rowDrawable = R.drawable.localflight_widget_row_light
      )
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
