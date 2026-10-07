#!/usr/bin/env python3
"""Offline checks for the The hub/child design. Standard library only.

What this DOES test:
  1. A Python model of the whitelist policy (label + floor->area + domain).
  2. The command-topic parsing rules the command bridge is meant to enforce.
  3. examples/emqx/acl.conf, evaluated top to bottom with first-match wins,
     against the proposed topic scheme and cross-unit / privileged topics.

What this does NOT test: the Jinja templates in the blueprints (no HA or
Jinja here), real EMQX behaviour, or the real registries. Keep the model in
sync with the `exposed` template by hand. Run: python3 tests/policy_model.py
"""
import re
import sys
from pathlib import Path

ACL = Path(__file__).resolve().parent.parent / "docs" / "emqx-acl-example.conf"
DOMAINS = {"light", "switch", "sensor", "binary_sensor", "fan", "scene", "cover"}
COVER_BLOCKED = {"garage", "gate", "door"}

# --------------------------------------------------------------------------
# 1. Whitelist policy model (mirror of the `exposed` template)
# --------------------------------------------------------------------------
FLOOR_AREAS = {
    "beta": ["beta", "l1_living"],
    "alpha": ["alpha", "l2_kitchen"],
    "shared": ["entry", "outdoors"],          # common floor, exposed to both units
    "meta": ["people", "roaming", "services", "staging"],
}
AREA_NAMES = {"beta": "Beta", "l1_living": "L1 Living Room", "alpha": "Alpha",
              "l2_kitchen": "L2 Kitchen", "entry": "Entry", "outdoors": "Outdoors",
              "people": "People", "roaming": "Roaming", "services": "Services",
              "staging": "Staging"}
UNIT_FLOORS = {"alpha": ["alpha"], "beta": ["beta"]}
UNIT_LABEL = {"alpha": "Live: Alpha", "beta": "Live: Beta"}
COMMON_LABEL = "Live: Shared"
COMMON_FLOORS = ["shared"]
COVER_CLASS = {"cover.alpha_blind": "blind", "cover.alpha_nodc": None, "cover.alpha_garage": "garage",
               "cover.alpha_gate": "gate", "cover.alpha_unavail": "blind", "cover.garage": "garage"}
UNAVAILABLE = {"cover.alpha_unavail"}
# entity -> (area or None, labels)
ENTITIES = {
    "light.beta_lamp": ("l1_living", {"Live: Beta"}),
    "light.alpha_lamp": ("alpha", {"Live: Alpha"}),
    "light.kitchen_pendant": ("l2_kitchen", {"Live: Alpha"}),
    "light.front_door": ("entry", {"Live: Shared"}),
    "light.alpha_color": ("alpha", {"Live: Alpha"}),      # color_temp + xy, currently off
    "light.alpha_rgb": ("alpha", {"Live: Alpha"}),        # rgbw
    "light.alpha_hs": ("alpha", {"Live: Alpha"}),         # hs
    "light.alpha_white": ("alpha", {"Live: Alpha"}),      # white only
    "light.alpha_onoff": ("alpha", {"Live: Alpha"}),      # onoff
    "light.alpha_noattr": ("alpha", {"Live: Alpha"}),     # no capability attributes at all
    "light.alpha_effects": ("alpha", {"Live: Alpha"}),    # has an effect list
    "fan.alpha_fan": ("alpha", {"Live: Alpha"}),          # speed, oscillate, direction, presets
    "fan.alpha_basic": ("alpha", {"Live: Alpha"}),        # on/off only
    "scene.alpha_movie": ("alpha", {"Live: Alpha"}),      # state "unknown" until used
    "cover.alpha_blind": ("alpha", {"Live: Alpha"}),      # open, close, stop, position
    "cover.alpha_nodc": ("alpha", {"Live: Alpha"}),       # open/close only, no device class
    "cover.alpha_garage": ("alpha", {"Live: Alpha"}),     # blocked class
    "cover.alpha_gate": ("alpha", {"Live: Alpha"}),       # blocked class
    "cover.alpha_unavail": ("alpha", {"Live: Alpha"}),    # unavailable right now
    "switch.entry_relay": ("entry", {"Live: Shared"}),
    "sensor.beta_temp": ("beta", {"Live: Beta"}),
    "light.unlabelled": ("alpha", set()),
    "light.no_area": (None, {"Live: Alpha"}),
    "light.staging_test": ("staging", {"Live: Alpha"}),
    "switch.services_pump": ("services", {"Live: Shared"}),
    "lock.front_door": ("entry", {"Live: Shared"}),
    "camera.front": ("entry", {"Live: Shared"}),
    "cover.garage": ("entry", {"Live: Shared"}),
    "light.old_live_label": ("alpha", {"Live"}),
    "light.shared_label_wrong_floor": ("alpha", {"Live: Shared"}),
    "light.alpha_label_on_commons": ("entry", {"Live: Alpha"}),
    "light.beta_label_on_alpha": ("alpha", {"Live: Beta"}),
}


def inputs(unit):
    """Blueprint inputs for one unit's automations."""
    return {"unit": unit, "unit_label": UNIT_LABEL[unit], "unit_floors": UNIT_FLOORS[unit],
            "common_label": COMMON_LABEL, "common_floors": COMMON_FLOORS,
            "hub_status_topic": "ha-unity/hub/status", "area_prefix_regex": "^L[0-9]+ ",
            "blocked_cover_classes": ["garage", "gate", "door"],
            "command_topic": f"{unit}/+/+/set"}


def exposed(unit):
    """Whitelist: (unit label AND unit floor) OR (common label AND common floor),
    and an allowlisted domain. Mirrors the `exposed` template."""
    ua = [a for f in UNIT_FLOORS[unit] for a in FLOOR_AREAS[f]]
    ca = [a for f in COMMON_FLOORS for a in FLOOR_AREAS[f]]
    out = set()
    for e, (area, labels) in ENTITIES.items():
        if e.split(".")[0] not in DOMAINS:
            continue
        if e.startswith("cover.") and (e in UNAVAILABLE or COVER_CLASS.get(e) in COVER_BLOCKED):
            continue
        if (UNIT_LABEL[unit] in labels and area in ua) or (COMMON_LABEL in labels and area in ca):
            out.add(e)
    return out


def check(name, cond, failures):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def test_policy(f):
    d, k = exposed("alpha"), exposed("beta")
    check("alpha sees its labelled devices", {"light.alpha_lamp", "light.kitchen_pendant"} <= d, f)
    check("beta sees its labelled devices", {"light.beta_lamp", "sensor.beta_temp"} <= k, f)
    check("Live: Shared on the common floor is visible to both",
          {"light.front_door", "switch.entry_relay"} <= d & k, f)
    check("no cross-unit leakage (beta lamp not in alpha)", "light.beta_lamp" not in d, f)
    check("no cross-unit leakage (alpha lamp not in beta)", "light.alpha_lamp" not in k, f)
    check("Live: Beta label on a Alpha-floor entity exposes nothing",
          "light.beta_label_on_alpha" not in d | k, f)
    check("Live: Shared on a Alpha-floor entity exposes nothing",
          "light.shared_label_wrong_floor" not in d | k, f)
    check("Live: Alpha on a common-floor entity exposes nothing (strict pairs)",
          "light.alpha_label_on_commons" not in d | k, f)
    check("unlabelled entity is not exposed", "light.unlabelled" not in d | k, f)
    check("retired plain 'Live' label is not exposed", "light.old_live_label" not in d | k, f)
    check("entity with no area is not exposed", "light.no_area" not in d | k, f)
    check("Meta floor areas are never exposed",
          not ({"light.staging_test", "switch.services_pump"} & (d | k)), f)
    check("lock and camera domains are never exposed",
          not ({"lock.front_door", "camera.front"} & (d | k)), f)
    check("covers of an allowed class are exposed",
          {"cover.alpha_blind", "cover.alpha_nodc"} <= d, f)
    check("garage and gate covers are blocked by default",
          not ({"cover.alpha_garage", "cover.alpha_gate", "cover.garage"} & (d | k)), f)
    check("a cover that is unavailable is never exposed", "cover.alpha_unavail" not in d, f)
    check("fans and scenes are exposed",
          {"fan.alpha_fan", "fan.alpha_basic", "scene.alpha_movie"} <= d, f)
    check("unknown unit has no config (KeyError, fail closed)",
          _raises(lambda: exposed("nobody")), f)


def _raises(fn):
    try:
        fn()
    except KeyError:
        return True
    return False


# --------------------------------------------------------------------------
# 2. Command-topic parsing model (mirror of the command bridge conditions)
# --------------------------------------------------------------------------
def bridge_accepts(unit, topic, payload="ON"):
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != unit or parts[3] != "set":
        return False
    entity = f"{parts[1]}.{parts[2]}"
    return parts[1] in {"light", "switch", "fan", "scene", "cover"} and entity in exposed(unit)


def test_bridge(f):
    check("bridge: exposed light accepted", bridge_accepts("alpha", "alpha/light/alpha_lamp/set"), f)
    check("bridge: common-space light accepted from beta",
          bridge_accepts("beta", "beta/light/front_door/set"), f)
    check("bridge: other unit's entity rejected",
          not bridge_accepts("alpha", "alpha/light/beta_lamp/set"), f)
    check("bridge: unlabelled rejected", not bridge_accepts("alpha", "alpha/light/unlabelled/set"), f)
    check("bridge: lock rejected", not bridge_accepts("alpha", "alpha/lock/front_door/set"), f)
    check("bridge: wrong prefix rejected", not bridge_accepts("alpha", "beta/light/beta_lamp/set"), f)
    check("bridge: extra level rejected", not bridge_accepts("alpha", "alpha/light/alpha_lamp/x/set"), f)
    check("bridge: ha/ topic as domain rejected", not bridge_accepts("alpha", "alpha/ha/light/set"), f)


# --------------------------------------------------------------------------
# 3. ACL file evaluation (first match wins; EMQX file authorizer semantics)
# --------------------------------------------------------------------------
def topic_matches(filt, topic):
    """MQTT filter match: `filt` may contain + and #."""
    fp, tp = filt.split("/"), topic.split("/")
    for i, seg in enumerate(fp):
        if seg == "#":
            return True
        if i >= len(tp):
            return False
        if seg != "+" and seg != tp[i]:
            return False
    return len(fp) == len(tp)


def sub_filter_covered(rule_filt, sub_filt):
    """A subscription filter is covered if every topic it matches is matched
    by the rule filter. Approximation: compare segment by segment."""
    rp, sp = rule_filt.split("/"), sub_filt.split("/")
    for i, rseg in enumerate(rp):
        if rseg == "#":
            return True
        if i >= len(sp):
            return False
        sseg = sp[i]
        if rseg == "+":
            if sseg == "#":
                return False
            continue
        if sseg != rseg:
            return False
    return len(rp) == len(sp)


RULE = re.compile(r"^\{(allow|deny),\s*(.*)\}\.\s*$")


def parse_acl(text):
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("%%"):
            continue
        m = RULE.match(line)
        if not m:
            raise ValueError("unparsed ACL line: " + line)
        action, rest = m.groups()
        who = "all"
        mu = re.search(r'\{username,\s*\{re,\s*"([^"]+)"\}\}', rest)
        if mu:
            who = re.compile(mu.group(1))
            rest = rest.replace(mu.group(0), "", 1)
        else:
            rest = rest.strip()
            rest = re.sub(r"^all\s*,?", "", rest).strip().lstrip(",")
        pubsub = "all"
        for word in ("publish", "subscribe"):
            if re.search(r"\b" + word + r"\b", rest):
                pubsub = word
        topics = []
        mb = re.search(r"\[(.*)\]", rest)
        if mb:
            for t in re.findall(r'(\{eq,\s*)?"([^"]+)"', mb.group(1)):
                topics.append(("eq" if t[0] else "filter", t[1]))
        rules.append((action, who, pubsub, topics))
    return rules


def acl_decision(rules, user, op, topic):
    for action, who, pubsub, topics in rules:
        if who != "all" and not who.search(user):
            continue
        if pubsub != "all" and pubsub != op:
            continue
        if not topics:  # bare {deny, all}
            return action
        for kind, t in topics:
            t = t.replace("${username}", user)
            if kind == "eq":
                hit = (t == topic)
            elif op == "publish":
                hit = topic_matches(t, topic)
            else:
                hit = sub_filter_covered(t, topic) or topic_matches(t, topic)
            if hit:
                return action
    return "deny"


def test_acl(f):
    rules = parse_acl(ACL.read_text())
    cases = [
        # (user, op, topic, expected)
        ("alpha", "subscribe", "alpha/ha/light/+/config", "allow"),
        ("alpha", "subscribe", "alpha/light/x/state", "allow"),
        ("alpha", "subscribe", "ha-unity/hub/status", "allow"),
        ("alpha", "publish", "alpha/light/x/set", "allow"),
        ("alpha", "publish", "alpha/climate/entry/target/set", "allow"),
        ("alpha", "publish", "alpha/status", "allow"),
        ("alpha", "publish", "beta/status", "deny"),
        ("alpha", "publish", "ha-unity/hub/status", "deny"),
        ("beta", "publish", "beta/status", "allow"),
        ("beta", "publish", "alpha/status", "deny"),
        ("alpha", "publish", "alpha/light/x/state", "deny"),
        ("alpha", "publish", "alpha/ha/light/x/config", "deny"),
        ("alpha", "publish", "alpha/climate/x/current", "deny"),
        ("alpha", "subscribe", "beta/#", "deny"),
        ("alpha", "subscribe", "beta/light/x/state", "deny"),
        ("alpha", "publish", "beta/light/x/set", "deny"),
        ("alpha", "subscribe", "zigbee2mqtt/#", "deny"),
        ("alpha", "subscribe", "zigbee2mqtt/alpha/x", "deny"),
        ("alpha", "publish", "zigbee2mqtt/alpha/x/set", "deny"),
        ("alpha", "publish", "zigbee2mqtt/bridge/request/permit_join", "deny"),
        ("alpha", "subscribe", "homeassistant/#", "deny"),
        ("alpha", "publish", "homeassistant/status", "deny"),
        ("alpha", "subscribe", "#", "deny"),
        ("alpha", "subscribe", "$SYS/#", "deny"),
        ("beta", "subscribe", "beta/ha/switch/+/config", "allow"),
        ("beta", "publish", "beta/switch/x/set", "allow"),
        ("beta", "publish", "alpha/light/x/set", "deny"),
        ("beta", "subscribe", "alpha/light/x/state", "deny"),
        ("beta", "subscribe", "zigbee2mqtt/beta/x", "deny"),
        ("hub", "publish", "alpha/ha/light/x/config", "allow"),
        ("hub", "publish", "beta/light/x/state", "allow"),
        ("hub", "subscribe", "alpha/light/x/set", "allow"),
        ("hub", "subscribe", "homeassistant/+/+/config", "allow"),
        ("hub", "publish", "ha-unity/hub/status", "allow"),
        ("hub", "publish", "homeassistant/light/x/config", "deny"),
        ("nobody", "subscribe", "alpha/#", "deny"),
        ("nobody", "publish", "anything/at/all", "deny"),
    ]
    for user, op, topic, expected in cases:
        got = acl_decision(rules, user, op, topic)
        check(f"acl: {user:7} {op:9} {topic} -> {expected}", got == expected, f)


if __name__ == "__main__":
    failures = []
    test_policy(failures)
    test_bridge(failures)
    test_acl(failures)
    print()
    if failures:
        print(f"{len(failures)} FAILED:")
        for x in failures:
            print("  -", x)
        sys.exit(1)
    print("all checks passed")
