# Security model

## What PropSense guarantees (by construction and by test)
- **Fail closed.** Exposure needs a label, a matching floor and an allowlisted
  domain. Missing or mismatched anything exposes nothing.
- **Strict label/floor pairs.** A unit label on a common-floor entity, or a
  common label on a unit floor, exposes nothing. A tagging mistake alone never
  leaks an entity.
- **No privileged domains.** Locks, covers, cameras, scripts, automations and
  anything else outside light, switch, sensor and binary sensor are not
  handled. The domain list is not an input.
- **Commands are validated twice.** The broker ACL limits what a unit may
  publish; the hub re-checks the whitelist on every command and uses hardcoded
  services. The entity comes from the topic, never the payload.
- **Revocation.** Removing a label, area or floor clears discovery within
  seconds (debounce) and stops commands immediately.

## What you must still do
1. **Broker ACLs.** Replace the broker's default allow-all rule with
   deny-by-default, one user per instance, unique client IDs. See
   [emqx-acl-example.conf](emqx-acl-example.conf). Units must **not** be able to
   read or write device-bridge topics, discovery prefixes or other units.
2. **Test the denials**, not just the allows: publish a command for another
   unit's entity, and to another unit's topic, and confirm nothing happens
   ([testing.md](testing.md)).
3. **Keep privileged integrations on the hub only** (radios, locks, cloud
   accounts, controllers). Units need no token to the hub.
4. **Treat label/area edits on the hub as access control.** Anyone who can
   change them on the hub changes what a unit can reach.
5. **Review before exposing anything that matters.** This is pre-1.0 software.

## Not covered
- A compromised hub exposes everything. A compromised unit can only read its
  own prefix and send validated commands.
- Cameras and locks are out of scope. If you add them, they need their own
  design (stream tokens, unlock auditing).
- Physical or radio-level isolation: units sharing one radio mesh can still
  affect each other's devices at the radio layer.
