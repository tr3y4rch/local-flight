package cc.beacontools.localflight.paidapp

import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import android.util.Base64
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.PurchasesUpdatedListener
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.StandardIntegrityException
import com.google.android.play.core.integrity.StandardIntegrityManager
import com.google.android.play.core.integrity.model.StandardIntegrityErrorCode
import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

private object PaidAppProofErrorCode {
  const val STORE_CANCELLED = "store_cancelled"
  const val STORE_UNAVAILABLE = "store_unavailable"
  const val OWNERSHIP_UNVERIFIED = "ownership_unverified"
  const val DEVICE_VERIFICATION_MISSING = "device_verification_missing"
  const val STORE_TIMEOUT = "store_timeout"
  const val UNSUPPORTED_BUILD = "unsupported_build"
  const val PURCHASE_PENDING = "purchase_pending"
}

private object PaidAppConfiguration {
  const val RELAY_ACCESS_PRODUCT_ID = "cc.beacontools.localflight.relay_access"
  const val PRODUCT_ID_METADATA = "cc.beacontools.localflight.RELAY_ACCESS_PRODUCT_ID"
  const val INTEGRITY_PROJECT_METADATA =
    "cc.beacontools.localflight.PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER"
  const val INTEGRITY_BINDING_VERSION = "localflight-relay-grant-v1"
}

private const val BILLING_TIMEOUT_MS = 20_000L
private const val PURCHASE_TIMEOUT_MS = 5 * 60_000L
private const val INTEGRITY_TIMEOUT_MS = 60_000L

private data class StoreConfiguration(
  val productId: String,
  val cloudProjectNumber: Long
)

private data class RelayPurchase(
  val state: String,
  val productId: String,
  val purchaseToken: String,
  val acknowledged: Boolean
) {
  fun asMap(): Map<String, Any> = mapOf(
    "owned" to (state == "purchased"),
    "state" to state,
    "productId" to productId,
    "purchaseToken" to purchaseToken,
    "acknowledged" to acknowledged
  )
}

public class LocalFlightPaidAppModule : Module() {
  private val billingRequestInFlight = AtomicBoolean(false)
  private val integrityRequestInFlight = AtomicBoolean(false)

  @Volatile
  private var integrityTokenProvider: StandardIntegrityManager.StandardIntegrityTokenProvider? = null

  override fun definition() = ModuleDefinition {
    Name("LocalFlightPaidApp")

    AsyncFunction("getFreshAppleAppTransactionProof") { promise: Promise ->
      promise.reject(
        PaidAppProofErrorCode.UNSUPPORTED_BUILD,
        "App Store ownership verification is unavailable on Android.",
        null
      )
    }

    AsyncFunction("queryGooglePlayRelayAccessPurchase") { promise: Promise ->
      val context = applicationContextOrReject(promise) ?: return@AsyncFunction
      if (!billingRequestInFlight.compareAndSet(false, true)) {
        promise.reject(
          PaidAppProofErrorCode.STORE_UNAVAILABLE,
          "Another Google Play request is already in progress.",
          null
        )
        return@AsyncFunction
      }
      queryRelayPurchase(context, promise)
    }

    AsyncFunction("purchaseGooglePlayRelayAccess") { promise: Promise ->
      val context = applicationContextOrReject(promise) ?: return@AsyncFunction
      val activity = appContext.currentActivity
      if (activity == null) {
        promise.reject(
          PaidAppProofErrorCode.UNSUPPORTED_BUILD,
          "Google Play purchasing requires an active Android screen.",
          null
        )
        return@AsyncFunction
      }
      if (!billingRequestInFlight.compareAndSet(false, true)) {
        promise.reject(
          PaidAppProofErrorCode.STORE_UNAVAILABLE,
          "Another Google Play request is already in progress.",
          null
        )
        return@AsyncFunction
      }
      purchaseRelayAccess(context, activity, promise)
    }

    AsyncFunction("requestGooglePlayIntegrityToken") {
        nonce: String,
        installId: String,
        activationGrant: String,
        promise: Promise ->
      val context = applicationContextOrReject(promise) ?: return@AsyncFunction
      if (
        nonce.isBlank() ||
        nonce.length > 1_024 ||
        installId.isBlank() ||
        installId.length > 128 ||
        activationGrant.isBlank() ||
        activationGrant.length > 2_048 ||
        nonce.indexOf(':') >= 0 ||
        installId.indexOf(':') >= 0 ||
        activationGrant.indexOf(':') >= 0
      ) {
        promise.reject(
          PaidAppProofErrorCode.OWNERSHIP_UNVERIFIED,
          "The Google Play verification request is invalid.",
          null
        )
        return@AsyncFunction
      }
      if (!integrityRequestInFlight.compareAndSet(false, true)) {
        promise.reject(
          PaidAppProofErrorCode.STORE_UNAVAILABLE,
          "Another Google Play verification is already in progress.",
          null
        )
        return@AsyncFunction
      }
      requestIntegrityToken(context, nonce, installId, activationGrant, promise)
    }
  }

  private fun applicationContextOrReject(promise: Promise): Context? {
    val context = appContext.reactContext?.applicationContext
    if (context == null) {
      promise.reject(
        PaidAppProofErrorCode.UNSUPPORTED_BUILD,
        "Android application context is unavailable in this build.",
        null
      )
    }
    return context
  }

  private fun readConfiguration(context: Context): StoreConfiguration {
    val applicationInfo = context.packageManager.getApplicationInfo(
      context.packageName,
      PackageManager.GET_META_DATA
    )
    val metadata = applicationInfo.metaData
    val configuredProduct = metadata
      ?.getString(PaidAppConfiguration.PRODUCT_ID_METADATA)
      ?.trim()
      .orEmpty()
    val projectNumber = metadata
      ?.getString(PaidAppConfiguration.INTEGRITY_PROJECT_METADATA)
      ?.trim()
      ?.removePrefix("project:")
      ?.toLongOrNull() ?: 0L
    return StoreConfiguration(
      productId = configuredProduct.ifBlank { PaidAppConfiguration.RELAY_ACCESS_PRODUCT_ID },
      cloudProjectNumber = projectNumber
    )
  }

  private fun createBillingClient(
    context: Context,
    purchasesUpdatedListener: PurchasesUpdatedListener
  ): BillingClient = BillingClient.newBuilder(context)
    .setListener(purchasesUpdatedListener)
    .enablePendingPurchases(
      PendingPurchasesParams.newBuilder()
        .enableOneTimeProducts()
        .build()
    )
    .enableAutoServiceReconnection()
    .build()

  private fun queryRelayPurchase(context: Context, promise: Promise) {
    val completed = AtomicBoolean(false)
    val handler = Handler(Looper.getMainLooper())
    val timeoutToken = Any()
    lateinit var client: BillingClient

    fun finish(block: () -> Unit) {
      if (!completed.compareAndSet(false, true)) return
      handler.removeCallbacksAndMessages(timeoutToken)
      billingRequestInFlight.set(false)
      client.endConnection()
      block()
    }

    client = createBillingClient(context, PurchasesUpdatedListener { _, _ -> })
    scheduleTimeout(handler, timeoutToken, BILLING_TIMEOUT_MS) {
      finish {
        promise.reject(
          PaidAppProofErrorCode.STORE_TIMEOUT,
          "Google Play purchase lookup timed out.",
          null
        )
      }
    }
    startBillingConnection(
      client,
      isFinished = { completed.get() },
      finish = ::finish,
      promise = promise
    ) {
      queryRelayPurchaseOnConnected(client, readConfiguration(context).productId) { result, purchase ->
        if (result.responseCode != BillingClient.BillingResponseCode.OK) {
          finish { rejectBillingResult(result, promise) }
          return@queryRelayPurchaseOnConnected
        }
        finish { promise.resolve(purchase.asMap()) }
      }
    }
  }

  private fun purchaseRelayAccess(context: Context, activity: Activity, promise: Promise) {
    val completed = AtomicBoolean(false)
    val handler = Handler(Looper.getMainLooper())
    val timeoutToken = Any()
    val productId = readConfiguration(context).productId
    lateinit var client: BillingClient

    fun finish(block: () -> Unit) {
      if (!completed.compareAndSet(false, true)) return
      handler.removeCallbacksAndMessages(timeoutToken)
      billingRequestInFlight.set(false)
      client.endConnection()
      block()
    }

    fun handlePurchases(result: BillingResult, purchases: List<Purchase>?) {
      if (result.responseCode == BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED) {
        queryRelayPurchaseOnConnected(client, productId) { retryResult, purchase ->
          if (retryResult.responseCode != BillingClient.BillingResponseCode.OK) {
            finish { rejectBillingResult(retryResult, promise) }
          } else {
            finishWithPurchase(purchase, promise, ::finish)
          }
        }
        return
      }
      if (result.responseCode != BillingClient.BillingResponseCode.OK) {
        finish { rejectBillingResult(result, promise) }
        return
      }
      val purchase = selectRelayPurchase(productId, purchases.orEmpty())
      if (purchase == null) {
        finish {
          promise.reject(
            PaidAppProofErrorCode.OWNERSHIP_UNVERIFIED,
            "Google Play did not return the Relay Access purchase.",
            null
          )
        }
        return
      }
      finishWithPurchase(purchase, promise, ::finish)
    }

    client = createBillingClient(context, PurchasesUpdatedListener(::handlePurchases))
    scheduleTimeout(handler, timeoutToken, PURCHASE_TIMEOUT_MS) {
      finish {
        promise.reject(
          PaidAppProofErrorCode.STORE_TIMEOUT,
          "Google Play purchasing timed out.",
          null
        )
      }
    }
    startBillingConnection(
      client,
      isFinished = { completed.get() },
      finish = ::finish,
      promise = promise
    ) {
      queryRelayPurchaseOnConnected(client, productId) { queryResult, currentPurchase ->
        if (completed.get()) return@queryRelayPurchaseOnConnected
        if (queryResult.responseCode != BillingClient.BillingResponseCode.OK) {
          finish { rejectBillingResult(queryResult, promise) }
          return@queryRelayPurchaseOnConnected
        }
        when (currentPurchase.state) {
          "purchased" -> finish { promise.resolve(currentPurchase.asMap()) }
          "pending" -> finish {
            promise.reject(
              PaidAppProofErrorCode.PURCHASE_PENDING,
              "The Google Play purchase is still pending.",
              null
            )
          }
          else -> queryProductAndLaunch(
            client,
            productId,
            activity,
            promise,
            { completed.get() },
            ::finish
          )
        }
      }
    }
  }

  private fun startBillingConnection(
    client: BillingClient,
    isFinished: () -> Boolean,
    finish: (() -> Unit) -> Unit,
    promise: Promise,
    onReady: () -> Unit
  ) {
    client.startConnection(object : BillingClientStateListener {
      override fun onBillingSetupFinished(result: BillingResult) {
        if (isFinished()) return
        if (result.responseCode == BillingClient.BillingResponseCode.OK) {
          onReady()
        } else {
          finish { rejectBillingResult(result, promise) }
        }
      }

      override fun onBillingServiceDisconnected() {
        // Auto-reconnection handles a disconnect during an active API call. If
        // setup has not completed, the outer timeout produces a stable result.
      }
    })
  }

  private fun queryRelayPurchaseOnConnected(
    client: BillingClient,
    productId: String,
    callback: (BillingResult, RelayPurchase) -> Unit
  ) {
    val params = QueryPurchasesParams.newBuilder()
      .setProductType(BillingClient.ProductType.INAPP)
      .build()
    client.queryPurchasesAsync(params) { result, purchases ->
      val selected = selectRelayPurchase(productId, purchases)
      callback(result, selected ?: RelayPurchase("not_owned", productId, "", false))
    }
  }

  private fun selectRelayPurchase(productId: String, purchases: List<Purchase>): RelayPurchase? {
    val matches = purchases.filter { purchase -> productId in purchase.products }
    val selected = matches.firstOrNull { it.purchaseState == Purchase.PurchaseState.PURCHASED }
      ?: matches.firstOrNull { it.purchaseState == Purchase.PurchaseState.PENDING }
      ?: return null
    val state = when (selected.purchaseState) {
      Purchase.PurchaseState.PURCHASED -> "purchased"
      Purchase.PurchaseState.PENDING -> "pending"
      else -> "not_owned"
    }
    return RelayPurchase(
      state = state,
      productId = productId,
      purchaseToken = if (state == "not_owned") "" else selected.purchaseToken,
      acknowledged = selected.isAcknowledged
    )
  }

  private fun queryProductAndLaunch(
    client: BillingClient,
    productId: String,
    activity: Activity,
    promise: Promise,
    isFinished: () -> Boolean,
    finish: (() -> Unit) -> Unit
  ) {
    val product = QueryProductDetailsParams.Product.newBuilder()
      .setProductId(productId)
      .setProductType(BillingClient.ProductType.INAPP)
      .build()
    val params = QueryProductDetailsParams.newBuilder()
      .setProductList(listOf(product))
      .build()
    client.queryProductDetailsAsync(params) { result, detailsResult ->
      if (isFinished()) return@queryProductDetailsAsync
      if (result.responseCode != BillingClient.BillingResponseCode.OK) {
        finish { rejectBillingResult(result, promise) }
        return@queryProductDetailsAsync
      }
      val details = detailsResult.productDetailsList.firstOrNull { it.productId == productId }
      if (details == null) {
        finish {
          promise.reject(
            PaidAppProofErrorCode.UNSUPPORTED_BUILD,
            "Relay Access is not configured for this Google Play build.",
            null
          )
        }
        return@queryProductDetailsAsync
      }
      Handler(Looper.getMainLooper()).post {
        if (isFinished()) return@post
        val productParamsBuilder = BillingFlowParams.ProductDetailsParams.newBuilder()
          .setProductDetails(details)
        selectedOfferToken(details)?.let(productParamsBuilder::setOfferToken)
        val flowParams = BillingFlowParams.newBuilder()
          .setProductDetailsParamsList(listOf(productParamsBuilder.build()))
          .build()
        val launchResult = client.launchBillingFlow(activity, flowParams)
        if (launchResult.responseCode != BillingClient.BillingResponseCode.OK) {
          finish { rejectBillingResult(launchResult, promise) }
        }
      }
    }
  }

  private fun selectedOfferToken(details: ProductDetails): String? =
    details.oneTimePurchaseOfferDetailsList
      ?.firstOrNull()
      ?.offerToken
      ?.takeIf { it.isNotBlank() }

  private fun finishWithPurchase(
    purchase: RelayPurchase,
    promise: Promise,
    finish: (() -> Unit) -> Unit
  ) {
    when (purchase.state) {
      "purchased" -> finish { promise.resolve(purchase.asMap()) }
      "pending" -> finish {
        promise.reject(
          PaidAppProofErrorCode.PURCHASE_PENDING,
          "The Google Play purchase is still pending.",
          null
        )
      }
      else -> finish {
        promise.reject(
          PaidAppProofErrorCode.OWNERSHIP_UNVERIFIED,
          "Google Play could not confirm the Relay Access purchase.",
          null
        )
      }
    }
  }

  private fun rejectBillingResult(result: BillingResult, promise: Promise) {
    val errorCode = when (result.responseCode) {
      BillingClient.BillingResponseCode.USER_CANCELED -> PaidAppProofErrorCode.STORE_CANCELLED
      BillingClient.BillingResponseCode.FEATURE_NOT_SUPPORTED,
      BillingClient.BillingResponseCode.DEVELOPER_ERROR -> PaidAppProofErrorCode.UNSUPPORTED_BUILD
      BillingClient.BillingResponseCode.ITEM_NOT_OWNED -> PaidAppProofErrorCode.OWNERSHIP_UNVERIFIED
      else -> PaidAppProofErrorCode.STORE_UNAVAILABLE
    }
    val message = when (errorCode) {
      PaidAppProofErrorCode.STORE_CANCELLED -> "Google Play purchasing was cancelled."
      PaidAppProofErrorCode.UNSUPPORTED_BUILD -> "Google Play purchasing is unavailable in this build."
      PaidAppProofErrorCode.OWNERSHIP_UNVERIFIED -> "Google Play could not confirm this purchase."
      else -> "Google Play is unavailable right now."
    }
    promise.reject(errorCode, message, null)
  }

  private fun requestIntegrityToken(
    context: Context,
    nonce: String,
    installId: String,
    activationGrant: String,
    promise: Promise
  ) {
    val configuration = readConfiguration(context)
    if (configuration.cloudProjectNumber <= 0L) {
      integrityRequestInFlight.set(false)
      promise.reject(
        PaidAppProofErrorCode.UNSUPPORTED_BUILD,
        "Play Integrity is not configured in this build.",
        null
      )
      return
    }

    val requestHash = integrityRequestHash(
      nonce = nonce,
      installId = installId,
      activationGrant = activationGrant
    )
    val completed = AtomicBoolean(false)
    val handler = Handler(Looper.getMainLooper())
    val timeoutToken = Any()
    val manager = IntegrityManagerFactory.createStandard(context)

    fun finish(block: () -> Unit) {
      if (!completed.compareAndSet(false, true)) return
      handler.removeCallbacksAndMessages(timeoutToken)
      integrityRequestInFlight.set(false)
      block()
    }

    fun request(provider: StandardIntegrityManager.StandardIntegrityTokenProvider, mayRefresh: Boolean) {
      if (completed.get()) return
      val request = StandardIntegrityManager.StandardIntegrityTokenRequest.builder()
        .setRequestHash(requestHash)
        .build()
      provider.request(request)
        .addOnSuccessListener { response ->
          finish {
            promise.resolve(
              mapOf(
                "token" to response.token(),
                "requestHash" to requestHash
              )
            )
          }
        }
        .addOnFailureListener { error ->
          if (
            mayRefresh &&
            error is StandardIntegrityException &&
            error.errorCode == StandardIntegrityErrorCode.INTEGRITY_TOKEN_PROVIDER_INVALID
          ) {
            integrityTokenProvider = null
            prepareIntegrityProvider(manager, configuration.cloudProjectNumber, ::finish, promise) {
              request(it, false)
            }
          } else {
            finish { rejectIntegrityError(error, promise) }
          }
        }
    }

    scheduleTimeout(handler, timeoutToken, INTEGRITY_TIMEOUT_MS) {
      finish {
        promise.reject(
          PaidAppProofErrorCode.STORE_TIMEOUT,
          "Play Integrity verification timed out.",
          null
        )
      }
    }

    val existingProvider = integrityTokenProvider
    if (existingProvider != null) {
      request(existingProvider, true)
    } else {
      prepareIntegrityProvider(manager, configuration.cloudProjectNumber, ::finish, promise) { provider ->
        if (completed.get()) return@prepareIntegrityProvider
        integrityTokenProvider = provider
        request(provider, true)
      }
    }
  }

  private fun prepareIntegrityProvider(
    manager: StandardIntegrityManager,
    cloudProjectNumber: Long,
    finish: (() -> Unit) -> Unit,
    promise: Promise,
    onReady: (StandardIntegrityManager.StandardIntegrityTokenProvider) -> Unit
  ) {
    val request = StandardIntegrityManager.PrepareIntegrityTokenRequest.builder()
      .setCloudProjectNumber(cloudProjectNumber)
      .build()
    manager.prepareIntegrityToken(request)
      .addOnSuccessListener(onReady)
      .addOnFailureListener { error -> finish { rejectIntegrityError(error, promise) } }
  }

  private fun rejectIntegrityError(error: Exception, promise: Promise) {
    val integrityCode = (error as? StandardIntegrityException)?.errorCode
    val code = when (integrityCode) {
      StandardIntegrityErrorCode.CLOUD_PROJECT_NUMBER_IS_INVALID,
      StandardIntegrityErrorCode.REQUEST_HASH_TOO_LONG,
      StandardIntegrityErrorCode.APP_UID_MISMATCH -> PaidAppProofErrorCode.UNSUPPORTED_BUILD
      StandardIntegrityErrorCode.API_NOT_AVAILABLE,
      StandardIntegrityErrorCode.PLAY_STORE_NOT_FOUND,
      StandardIntegrityErrorCode.PLAY_STORE_VERSION_OUTDATED,
      StandardIntegrityErrorCode.PLAY_SERVICES_NOT_FOUND,
      StandardIntegrityErrorCode.PLAY_SERVICES_VERSION_OUTDATED,
      StandardIntegrityErrorCode.APP_NOT_INSTALLED,
      StandardIntegrityErrorCode.CANNOT_BIND_TO_SERVICE ->
        PaidAppProofErrorCode.DEVICE_VERIFICATION_MISSING
      else -> PaidAppProofErrorCode.STORE_UNAVAILABLE
    }
    val message = when (code) {
      PaidAppProofErrorCode.UNSUPPORTED_BUILD -> "Play Integrity is not configured for this build."
      PaidAppProofErrorCode.DEVICE_VERIFICATION_MISSING ->
        "Google Play device verification is unavailable."
      else -> "Google Play could not verify this device right now."
    }
    promise.reject(code, message, error)
  }

  private fun integrityRequestHash(
    nonce: String,
    installId: String,
    activationGrant: String
  ): String {
    val canonical =
      "${PaidAppConfiguration.INTEGRITY_BINDING_VERSION}:$nonce:$installId:$activationGrant"
    val digest = MessageDigest.getInstance("SHA-256")
      .digest(canonical.toByteArray(StandardCharsets.UTF_8))
    return Base64.encodeToString(
      digest,
      Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING
    )
  }

  private fun scheduleTimeout(
    handler: Handler,
    token: Any,
    delayMs: Long,
    callback: () -> Unit
  ) {
    handler.postAtTime(
      callback,
      token,
      android.os.SystemClock.uptimeMillis() + delayMs
    )
  }
}
