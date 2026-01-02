# Changelog

All notable changes to the Ampæra Home Assistant integration.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-01-01

### Added
- Push architecture: HA pushes telemetry to Ampæra cloud
- Device discovery: Automatic detection of compatible HA devices
- Device sync: Keeps HA devices synchronized with Ampæra
- Command polling: Remote control from Ampæra dashboard
- Diagnostics: Debug info via Developer Tools
- Services: `ampaera.force_sync` and `ampaera.push_telemetry`
- Multi-region support: NO1-NO5 Norwegian grid regions
- Translations: English and Norwegian (Bokmål)
- Entity mapping: Groups sensors under parent devices

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.21.0+

## [Previous versions]

Prior to v1.0.0, the integration used version numbers matching the amp repo.
See [amp releases](https://github.com/morteng/amp/releases) for historical changes.
