# How PropSense works

## Roles
- **Hub:** the Home Assistant instance that owns devices and integrations.
- **Unit:** a Home Assistant instance that only receives what the hub publishes.
- **Broker:** one MQTT broker all instances connect to.

## Topics (per unit, prefix `<unit>`)
```
<unit>/ha/<component>/<object_id>/config   retained discovery (unit discovery prefix: <unit>/ha)
<unit>/<domain>/<object_id>/state          retained state
<unit>/<domain>/<object_id>/availability   online / offline per entity
<unit>/<domain>/<object_id>/set            commands from the unit
<unit>/climate/<room>/target/set           climate setpoint (climate blueprint)
<unit>/status                              the unit's own birth and will
propsense/hub/status                       retained hub marker (input: hub_status_topic)
```
Entities are available on a unit only while the entity's own availability is
`online` **and** the hub marker reads `online`.

## What runs when (no polling)
| Blueprint | Triggers | Does |
|---|---|---|
| publish discovery | HA start; any entity, device, area, floor or label registry change (5 s debounce); every 6 h | Publishes discovery for exposed entities; clears it for entities that stopped qualifying |
| publish state | each `state_changed` of an exposed entity; the same registry events; every 6 h | Publishes retained state and availability |
| command bridge | MQTT message on `<unit>/+/+/set` | Re-checks the whitelist, then calls a hardcoded light or switch service |
| climate | registry events, state changes of the two entities, and its command topic | Publishes a synthetic thermostat; clamps and applies setpoints |

## The whitelist
Evaluated identically in all blueprints (keep the `exposed` template in sync):

```
exposed(unit) = domain in {light, switch, sensor, binary_sensor} and
  ( unit label   and area on one of the unit's floors
  or common label and area on one of the common floors )
```
An entity's area is its own area, or its device's area if it has none.
`tests/policy_model.py` is the reference model of this rule.

## Rooms
Each discovery payload includes a `device` block (identifier scoped to the
unit) and `suggested_area`. A unit adopts an existing area of that name, or
creates it (floorless) if missing. If `area_prefix_regex` matches the hub's
area name, the prefix is stripped. Areas on the common floors send their own
name unchanged. Anything else sends no suggested area.

## Names
MQTT entities that belong to a device are named "<device> <entity name>". To
avoid doubled names, the entity name is sent as `null` when the entity is the
device, and otherwise as its friendly name minus the device-name prefix.
