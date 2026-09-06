import ExpoModulesCore
import StoreKit

private enum PaidAppProofErrorCode {
  static let storeCancelled = "store_cancelled"
  static let storeUnavailable = "store_unavailable"
  static let ownershipUnverified = "ownership_unverified"
  static let deviceVerificationMissing = "device_verification_missing"
  static let storeTimeout = "store_timeout"
  static let unsupportedBuild = "unsupported_build"
  static let purchasePending = "purchase_pending"
}

private func paidAppProofError(
  _ code: String,
  _ description: String,
  cause: Error? = nil
) -> Exception {
  let exception = Exception(
    name: "LocalFlightPaidAppError",
    description: description,
    code: code
  )
  exception.cause = cause
  return exception
}

private func isStoreCancellation(_ error: Error) -> Bool {
  if let storeKitError = error as? StoreKitError,
     case .userCancelled = storeKitError {
    return true
  }
  let nsError = error as NSError
  return nsError.domain == SKError.errorDomain && nsError.code == SKError.paymentCancelled.rawValue
}

private func isStoreTimeout(_ error: Error) -> Bool {
  let nsError = error as NSError
  if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorTimedOut {
    return true
  }
  if let storeKitError = error as? StoreKitError,
     case let .networkError(networkError) = storeKitError {
    return (networkError as NSError).code == NSURLErrorTimedOut
  }
  return false
}

public final class LocalFlightPaidAppModule: Module {
  public func definition() -> ModuleDefinition {
    Name("LocalFlightPaidApp")

    AsyncFunction("getFreshAppleAppTransactionProof") { () async throws -> [String: String] in
      guard #available(iOS 16.0, *) else {
        throw paidAppProofError(
          PaidAppProofErrorCode.unsupportedBuild,
          "App purchase verification requires iOS 16 or later."
        )
      }

      // This bridge is invoked only by an explicit setup, verify, restore, or
      // move action. AppTransaction.refresh() may show an App Store prompt, so
      // callers must never invoke it from background or automatic refresh work.
      let result: VerificationResult<AppTransaction>
      do {
        result = try await AppTransaction.refresh()
      } catch {
        if isStoreCancellation(error) {
          throw paidAppProofError(
            PaidAppProofErrorCode.storeCancelled,
            "App Store verification was cancelled.",
            cause: error
          )
        }
        if isStoreTimeout(error) {
          throw paidAppProofError(
            PaidAppProofErrorCode.storeTimeout,
            "App Store verification timed out.",
            cause: error
          )
        }
        throw paidAppProofError(
          PaidAppProofErrorCode.storeUnavailable,
          "App Store ownership could not be refreshed. Try again when the store is reachable.",
          cause: error
        )
      }
      guard case .verified = result else {
        throw paidAppProofError(
          PaidAppProofErrorCode.ownershipUnverified,
          "The App Store could not verify this app purchase."
        )
      }
      guard let deviceVerificationID = AppStore.deviceVerificationID else {
        throw paidAppProofError(
          PaidAppProofErrorCode.deviceVerificationMissing,
          "App Store device verification is unavailable."
        )
      }
      return [
        "signedAppTransaction": result.jwsRepresentation,
        "deviceVerificationId": deviceVerificationID.uuidString.lowercased()
      ]
    }

    AsyncFunction("queryGooglePlayRelayAccessPurchase") { () throws -> [String: Any] in
      throw paidAppProofError(
        PaidAppProofErrorCode.unsupportedBuild,
        "Google Play purchasing is unavailable on iOS."
      )
    }

    AsyncFunction("purchaseGooglePlayRelayAccess") { () throws -> [String: Any] in
      throw paidAppProofError(
        PaidAppProofErrorCode.unsupportedBuild,
        "Google Play purchasing is unavailable on iOS."
      )
    }

    AsyncFunction("requestGooglePlayIntegrityToken") {
        (_nonce: String, _installId: String, _activationGrant: String) throws -> [String: String] in
      throw paidAppProofError(
        PaidAppProofErrorCode.unsupportedBuild,
        "Google Play device verification is unavailable on iOS."
      )
    }
  }
}
