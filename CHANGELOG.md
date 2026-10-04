# Changelog

## 0.1.0 (unreleased)
- Blueprints: publish discovery, publish state, command bridge (lights, switches), synthetic climate.
- Whitelist: unit label + unit floors, or common label + common floors; allowlisted domains only.
- Optional `area_prefix_regex` and `hub_status_topic` inputs.
- Climate: optional target sensor, optional mode sensor (hvac action), `temperature_unit` input, optional guest-override expiry with a user-supplied action; runs in parallel mode; state changes filtered from `state_changed`.
- Offline test suites (policy model and rendered templates); example broker ACL; hub heartbeat example.
