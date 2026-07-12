# Third-Party Notices

Local Flight bundles a small number of open-source font files so the native,
LAN browser, kiosk, and mobile design language can stay consistent without
loading fonts from a CDN at runtime.

## Bundled Fonts

### Audiowide

- Files: `src/localflight/ui/static/fonts/Audiowide-Regular.ttf`, `mobile/assets/fonts/Audiowide-Regular.ttf`
- Designer: Astigmatic
- Copyright: Copyright 2012 Brian J. Bonislawsky DBA Astigmatic (AOETI)
- Source: https://github.com/google/fonts/tree/main/ofl/audiowide
- License: SIL Open Font License 1.1
- Local license copies: `src/localflight/ui/static/fonts/OFL-Audiowide.txt`, `mobile/assets/fonts/OFL-Audiowide.txt`

### DM Sans

- Files: `src/localflight/ui/static/fonts/DMSans.ttf`, `mobile/assets/fonts/DMSans.ttf`
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
