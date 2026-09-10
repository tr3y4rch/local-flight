# Third-Party Notices

Local Flight bundles a small number of open-source font files so the native,
LAN browser, kiosk, and mobile design language can stay consistent without
loading fonts from a CDN at runtime. It can also display information obtained
from external data services. The Local Flight MIT license covers the software,
not provider data, API access, or provider trademarks. Those remain subject to
the provider's terms and the subscription or marketplace plan used to obtain
them.

## Bundled Fonts

### Audiowide

- Files: `src/localflight/ui/static/fonts/Audiowide-Regular.ttf`, `mobile/assets/fonts/Audiowide-Regular.ttf`
- Designer: Astigmatic
- Copyright: Copyright 2012 Brian J. Bonislawsky DBA Astigmatic (AOETI)
- Source: https://github.com/google/fonts/tree/main/ofl/audiowide
- License: SIL Open Font License 1.1
- Local license copies: `src/localflight/ui/static/fonts/OFL-Audiowide.txt`, `mobile/assets/fonts/OFL-Audiowide.txt`

### DM Sans

- Files: `src/localflight/ui/static/fonts/DMSans.ttf`, `mobile/assets/fonts/DMSans.ttf`; static weights `src/localflight/ui/static/fonts/DMSans-{Regular,Bold,ExtraBold,Black}.ttf` are generated from the variable font by `scripts/build_static_ui_fonts.py` for the native Qt shell
- Designer: Colophon Foundry
- Copyright: Copyright 2014 The DM Sans Project Authors
- Source: https://github.com/googlefonts/dm-fonts
- License: SIL Open Font License 1.1
- Local license copies: `src/localflight/ui/static/fonts/OFL-DMSans.txt`, `mobile/assets/fonts/OFL-DMSans.txt`

### Space Mono

- Files: `src/localflight/ui/static/fonts/SpaceMono-Regular.ttf`, `src/localflight/ui/static/fonts/SpaceMono-Bold.ttf`, `mobile/assets/fonts/SpaceMono-Regular.ttf`, `mobile/assets/fonts/SpaceMono-Bold.ttf`
- Designer: Colophon Foundry
- Copyright: Copyright 2016 The Space Mono Project Authors
- Source: https://github.com/googlefonts/spacemono
- License: SIL Open Font License 1.1
- Local license copies: `src/localflight/ui/static/fonts/OFL-SpaceMono.txt`, `mobile/assets/fonts/OFL-SpaceMono.txt`

The bundled font files are not modified. If either family is modified later,
review the SIL Open Font License reserved-font-name requirements before
redistributing the changed files.

## Aviation Data Services

These services are not bundled with Local Flight. They are contacted only when
the corresponding data route or feature is configured. Beacon-managed access
uses Beacon's provider credentials and shared cache; Bring Your Own Keys (BYOK)
uses the credentials and provider agreement of the person operating that Local
Flight installation. Beacon-managed AeroDataBox and AviationStack schedule use
is backed by paid commercial subscriptions. This notice does not transfer or
expand any provider-data rights to Local Flight users.

### AeroDataBox

- Used for: primary real-world airport schedules and flight-board fields
- Access: direct subscription, API.Market, or RapidAPI, depending on configuration
- Terms: https://aerodatabox.com/terms
- Privacy: https://aerodatabox.com/privacy

### AviationStack

- Used for: optional missing-field enrichment and schedule fallback
- Access: APILayer/AviationStack subscription
- Terms: https://www.ideracorp.com/Legal/APILayer/Marketplace-Terms-of-Use
- Privacy: https://aviationstack.com/privacy-policy

### ADS-B Exchange / JETNET

- Used for: optional live nearby-aircraft radar data
- Access: BYOK, or Beacon-managed access only when the applicable provider agreement expressly permits it
- Terms: https://www.jetnet.com/legal/terms-of-use

### OpenSky Network

- Used for: optional radar fallback where the configured use is permitted
- Terms: https://opensky-network.org/about/terms-of-use
- Privacy: https://opensky-network.org/about/privacy

### VATSIM

- Used for: public virtual-network traffic, flight plans, and weather in VATSIM mode
- Privacy: https://vatsim.net/privacy-policy

### Aviation Weather Center

- Used for: public METAR weather from aviationweather.gov
- Source: https://aviationweather.gov/data/api/

All aviation information is presented for informational display only. It is not
an official aviation source and must not be used for navigation, dispatch,
air-traffic control, flight operations, or safety decisions.

## Public Data Sources

Local Flight can optionally fetch or cache public aviation/map data for the
radar display. These sources are not bundled as executable code, but their
attribution and license terms matter when their data is shown or cached.

### OurAirports

- Used for: airport and runway reference metadata when locally cached or bundled
- Source: https://ourairports.com/data/
- License: public domain, per OurAirports data page

### OpenStreetMap / Overpass

- Used for: optional simplified airport surface and map geometry
- Source: https://www.openstreetmap.org/
- Attribution: © OpenStreetMap contributors
- License: https://www.openstreetmap.org/copyright

### Terrain Tiles on AWS

- Used for: optional low-detail radar terrain/relief layer
- Source: https://registry.opendata.aws/terrain-tiles/
- Attribution: Terrain Tiles on AWS
