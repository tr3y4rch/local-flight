require "json"

package = JSON.parse(File.read(File.join(__dir__, "..", "package.json")))

Pod::Spec.new do |s|
  s.name = "LocalFlightWidgetBridge"
  s.version = package["version"]
  s.summary = package["description"]
  s.description = package["description"]
  s.license = "MIT"
  s.author = "Beacon Tools"
  s.homepage = "https://beacontools.cc/local-flight"
  s.platforms = { :ios => "15.1" }
  s.swift_version = "5.9"
  s.source = { :git => "https://github.com/tr3y4rch/local-flight.git" }
  s.static_framework = true

  s.dependency "ExpoModulesCore"
  s.source_files = "**/*.{h,m,mm,swift}"
end
