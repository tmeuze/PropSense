#!/usr/bin/env python3
"""Render the REAL template strings from the blueprints with Jinja2 against
stubbed Home Assistant functions, and compare with tests/policy_model.py.

Needs PyYAML and Jinja2:  python tests/render_blueprints.py
(any venv with PyYAML and Jinja2 installed)

What this proves: the template syntax is valid Jinja, the logic gives the
intended result, and the three blueprints agree with each other and with the
Python model. What it does NOT prove: that HA's own functions (floor_areas,
label_entities, area_id, state_attr) behave like the stubs below, that HA's
filters (to_json, combine, float(none)) match, or anything about EMQX. Those
are covered by docs/policy-test-plan.md on a real instance.
"""
import ast
import json
import re
import sys
from pathlib import Path

import jinja2
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy_model as pm  # noqa: E402

BP = Path(__file__).resolve().parent.parent / "blueprints" / "automation" / "propsense"


class Inp:
    def __init__(self, name):
        self.name = name


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!input", lambda l, n: Inp(l.construct_scalar(n)))


def load(name):
    return yaml.load((BP / name).read_text(), Loader=Loader)


# ---- stubs for HA template functions --------------------------------------
class State:
    def __init__(self, entity_id, state="on", **attrs):
        self.entity_id, self.state, self.attributes = entity_id, state, attrs
        self.domain = entity_id.split(".")[0]


def env_for(world_states, attrs=None):
    attrs = attrs or {}
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)

    def label_entities(label):
        return [e for e, (_a, labels) in pm.ENTITIES.items() if label in labels]

    class States(list):
        def __call__(self, eid):
            for s in self:
                if s.entity_id == eid:
                    return s.state
            return "unknown"

    states = States(world_states)
    env.globals.update(
        floor_areas=lambda f: pm.FLOOR_AREAS.get(f, []),
        label_entities=label_entities,
        area_id=lambda e: pm.ENTITIES.get(e, (None, set()))[0],
        state_attr=lambda e, a: attrs.get(e, {}).get(a),
        states=states,
    )
    def area_name(x):
        if x in pm.ENTITIES:
            x = pm.ENTITIES[x][0]
        return pm.AREA_NAMES.get(x)

    env.globals.update(
        area_name=area_name,
        device_id=lambda e: ("dev_" + e.split(".")[1]) if e in pm.ENTITIES else None,
        device_attr=lambda d, a: d.replace("dev_", "").replace("_", " ").title(),
    )
    env.tests["match"] = lambda v, pat: re.match(pat, str(v)) is not None
    env.filters["regex_replace"] = lambda v, pat, rep="": re.sub(pat, rep, str(v))
    env.filters["to_json"] = lambda v: json.dumps(v)
    env.filters["combine"] = lambda a, b: {**a, **b}
    return env


def render(env, tpl, ctx):
    """Render like HA's native templates: parse literals out of the result."""
    if not isinstance(tpl, str):
        return tpl
    out = env.from_string(tpl).render(**ctx).strip()
    if out == "":
        return ""
    try:
        return ast.literal_eval(out)
    except (ValueError, SyntaxError):
        return out


def run_vars(env, variables, inputs, ctx):
    ctx = dict(ctx)
    for k, v in variables.items():
        v = inputs[v.name] if isinstance(v, Inp) else v
        ctx[k] = render(env, v, ctx)
    return ctx


FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


WORLD = [State(e, "on") for e in pm.ENTITIES]
ATTRS = {
    "light.kitchen_pendant": {"friendly_name": "Kitchen Pendant", "brightness": 10,
                              "supported_color_modes": ["brightness"]},
    "light.front_door": {"friendly_name": "Front Door", "brightness": 255,
                         "supported_color_modes": ["brightness"]},
    "light.alpha_lamp": {"friendly_name": "Alpha Lamp", "brightness": 128,
                          "supported_color_modes": ["brightness"]},
    "switch.entry_relay": {"friendly_name": "Entry Relay"},
    "sensor.beta_temp": {"friendly_name": "Beta Temp Temperature", "device_class": "temperature",
                         "unit_of_measurement": "°F"},
}


def test_syntax_and_exposed():
    for name in ["propsense_publish_discovery.yaml", "propsense_publish_state.yaml",
                 "propsense_command_bridge.yaml", "propsense_climate.yaml"]:
        bp = load(name)
        check(f"{name}: parses and has blueprint+actions",
              "blueprint" in bp and "actions" in bp)
    env = env_for(WORLD, ATTRS)
    for unit in ["alpha", "beta"]:
        inputs = pm.inputs(unit)
        # discovery builds `exposed` inside an actions variables step
        disc = load("propsense_publish_discovery.yaml")
        step = next(a for a in disc["actions"] if "variables" in a)
        ctx = run_vars(env, disc["variables"], inputs, {})
        ctx = run_vars(env, step["variables"], inputs, ctx)
        e_disc = set(ctx["exposed"])
        state_bp = load("propsense_publish_state.yaml")
        e_state = set(run_vars(env, state_bp["variables"], inputs, {})["exposed"])
        cmd_bp = load("propsense_command_bridge.yaml")
        # command variables reference `trigger`; give a dummy topic
        e_cmd = set(run_vars(env, cmd_bp["variables"], inputs,
                             {"trigger": {"topic": f"{unit}/light/x/set", "payload": "ON"}})["exposed"])
        # the command bridge only handles light and switch
        model = pm.exposed(unit)
        check(f"{unit}: discovery exposed == model", e_disc == model)
        check(f"{unit}: state exposed == model", e_state == model)
        check(f"{unit}: command exposed == model restricted to light/switch",
              e_cmd == {e for e in model if e.split('.')[0] in ('light', 'switch')})
        check(f"{unit}: stale list is every non-exposed light/switch/sensor",
              set(ctx["stale"]) == {s.entity_id for s in WORLD
                                    if s.domain in pm.DOMAINS} - model)


def bridge(unit, topic, payload):
    """Run the command-bridge variables/conditions/choose; return service calls."""
    env = env_for(WORLD, ATTRS)
    bp = load("propsense_command_bridge.yaml")
    inputs = pm.inputs(unit)
    trig = {"topic": topic, "payload": payload}
    try:
        trig["payload_json"] = json.loads(payload)
    except ValueError:
        pass
    ctx = run_vars(env, bp["variables"], inputs, {"trigger": trig})
    for c in bp["conditions"]:
        if render(env, c["value_template"], ctx) is not True:
            return []
    for branch in bp["actions"][0]["choose"]:
        if render(env, branch["conditions"], ctx) is True:
            seq = branch["sequence"][0]
            data = seq.get("data")
            data = render(env, data, ctx) if data is not None else {}
            return [(seq["action"], render(env, seq["target"]["entity_id"], ctx), data)]
    return []


def test_bridge():
    L = "alpha/light/alpha_lamp/set"
    check("bridge: ON -> light.turn_on",
          bridge("alpha", L, '{"state":"ON"}')[0][:2] == ("light.turn_on", "light.alpha_lamp"))
    check("bridge: OFF -> light.turn_off",
          bridge("alpha", L, '{"state":"OFF"}')[0][0] == "light.turn_off")
    r = bridge("alpha", L, '{"state":"ON","brightness":9999}')
    check("bridge: brightness clamped to 255", r and r[0][2] == {"brightness": 255})
    r = bridge("alpha", L, '{"state":"ON","brightness":-5}')
    check("bridge: brightness clamped to 1", r and r[0][2] == {"brightness": 1})
    check("bridge: non-JSON payload ignored", bridge("alpha", L, "garbage") == [])
    check("bridge: unknown state ignored", bridge("alpha", L, '{"state":"TOGGLE"}') == [])
    check("bridge: other unit's entity ignored",
          bridge("alpha", "alpha/light/beta_lamp/set", '{"state":"ON"}') == [])
    check("bridge: unlabelled entity ignored",
          bridge("alpha", "alpha/light/unlabelled/set", '{"state":"ON"}') == [])
    check("bridge: lock ignored", bridge("alpha", "alpha/lock/front_door/set", "UNLOCK") == [])
    check("bridge: camera/cover ignored",
          bridge("alpha", "alpha/cover/garage/set", "ON") == [])
    check("bridge: Meta-floor entity ignored",
          bridge("alpha", "alpha/light/staging_test/set", '{"state":"ON"}') == [])
    check("bridge: common-space light works from beta",
          bridge("beta", "beta/light/front_door/set", '{"state":"ON"}')[0][1] == "light.front_door")
    check("bridge: common-space switch ON",
          bridge("alpha", "alpha/switch/entry_relay/set", "ON")[0][:2] == ("switch.turn_on", "switch.entry_relay"))
    check("bridge: wrong prefix ignored",
          bridge("alpha", "beta/light/beta_lamp/set", '{"state":"ON"}') == [])
    check("bridge: 5-level topic ignored",
          bridge("alpha", "alpha/light/alpha_lamp/x/set", '{"state":"ON"}') == [])
    check("bridge: alpha/ha/light/set not treated as an entity",
          bridge("alpha", "alpha/ha/light/set", '{"state":"ON"}') == [])
    check("bridge: JSON payload for a switch (needs ON/OFF word) ignored",
          bridge("alpha", "alpha/switch/entry_relay/set", '{"state":"ON"}') == [])


def test_payloads():
    env = env_for(WORLD, ATTRS)
    disc = load("propsense_publish_discovery.yaml")
    inputs = pm.inputs("alpha")
    loop = [a for a in disc["actions"] if "repeat" in a][1]["repeat"]["sequence"]
    var_step = loop[0]["variables"]
    choose = loop[1]["choose"]
    for eid, domain in [("light.alpha_lamp", "light"), ("switch.entry_relay", "switch"),
                        ("sensor.beta_temp", "sensor")]:
        ctx = run_vars(env, var_step, inputs, {"repeat": {"item": eid}, "unit": "alpha",
                                                "area_prefix": "^L[0-9]+ ", "hub_status_topic": "propsense/hub/status",
                                                "common_area_names": ["Entry", "Outdoors"]})
        branch = next(b for b in choose if domain in b["conditions"])
        data = branch["sequence"][0]["data"]
        topic = render(env, data["topic"], ctx)
        payload = json.loads(render(env, data["payload"], ctx) if isinstance(
            render(env, data["payload"], ctx), str) else json.dumps(render(env, data["payload"], ctx)))
        want = {"light": None, "switch": None, "sensor": "Temperature"}[domain]
        check(f"discovery {domain}: entity name is {want!r} (not doubled)", payload.get("name") == want)
        check(f"discovery {domain}: topic under child prefix",
              topic.startswith(f"alpha/ha/{domain}/"))
        check(f"discovery {domain}: valid JSON with unique_id and state_topic",
              payload["unique_id"].startswith("alpha_") and payload["state_topic"].startswith("alpha/"))
        check(f"discovery {domain}: availability requires propsense/hub/status",
              payload["availability_mode"] == "all"
              and {"topic": "propsense/hub/status"} in payload["availability"])
        if domain != "sensor":
            check(f"discovery {domain}: command topic is <base>/set",
                  payload.get("command_topic", "").endswith("/set"))
        else:
            check("discovery sensor: no command topic", "command_topic" not in payload)
    # suggested_area / device block
    ctx0 = {"unit": "alpha", "area_prefix": "^L[0-9]+ ", "hub_status_topic": "propsense/hub/status",
            "common_area_names": [pm.AREA_NAMES[a] for a in pm.FLOOR_AREAS["shared"]]}
    for eid, expect_sa in [("light.kitchen_pendant", "Kitchen"), ("light.alpha_lamp", None),
                           ("light.front_door", "Entry")]:
        ctx = run_vars(env, var_step, inputs, dict(ctx0, repeat={"item": eid}))
        dev = ctx["device"]
        check(f"suggested_area {eid}: {expect_sa}", dev.get("suggested_area") == expect_sa)
        check(f"device block {eid}: identifiers scoped to unit",
              dev["identifiers"][0].startswith("alpha_dev_"))
    # configurable inputs: custom hub topic; empty prefix rule strips nothing
    ctx = run_vars(env, var_step, inputs, {"repeat": {"item": "light.kitchen_pendant"}, "unit": "alpha",
                                            "area_prefix": "", "hub_status_topic": "custom/hub/up",
                                            "common_area_names": []})
    check("hub_status_topic input is used for availability",
          {"topic": "custom/hub/up"} in ctx["common"]["availability"])
    check("empty area_prefix_regex sends no suggested_area for a prefixed area",
          "suggested_area" not in ctx["device"])
    # state payloads
    st = load("propsense_publish_state.yaml")
    rep = [a for a in st["actions"] if "repeat" in a][0]["repeat"]["sequence"]
    pub = next(a for a in rep if a.get("action") == "mqtt.publish" and a["data"]["topic"].endswith("/state"))
    for eid, state, expect in [
        ("light.alpha_lamp", "on", {"state": "ON", "brightness": 128}),
        ("switch.entry_relay", "on", "ON"),
        ("sensor.beta_temp", "71", "71"),
    ]:
        world = [State(e, state if e == eid else "on") for e in pm.ENTITIES]
        e = env_for(world, ATTRS)
        ctx = run_vars(e, rep[0]["variables"], {}, {"repeat": {"item": eid}, "unit": "alpha"})
        out = render(e, pub["data"]["payload"], ctx)
        check(f"state payload {eid} == {expect}", out == expect or str(out) == str(expect))


def test_climate():
    bp = load("propsense_climate.yaml")
    base_inputs = dict(pm.inputs("alpha"), object="entry", min_temp=64, max_temp=80,
                       climate_entity="climate.rm_entry", current_sensor="sensor.entry_t",
                       command_topic="alpha/climate/entry/target/set")
    # climate entity must pass the same whitelist; add it to the stub world
    pm.ENTITIES["climate.rm_entry"] = ("entry", {"Live: Shared"})
    pm.ENTITIES["climate.rm_alpha_bed"] = ("alpha", set())  # not labelled
    pm.ENTITIES["climate.rm_beta_wrongunit"] = ("alpha", {"Live: Beta"})  # label/floor mismatch
    pm.ENTITIES["climate.rm_virtual"] = ("staging", {"Live: Alpha"})
    env = env_for(WORLD, ATTRS)
    cmd = bp["actions"][0]["choose"][0]
    for label, rm, topic, payload, expect in [
        ("in-range", "climate.rm_entry", "alpha/climate/entry/target/set", "72", 72.0),
        ("above max clamps to 80", "climate.rm_entry", "alpha/climate/entry/target/set", "95", 80.0),
        ("below min clamps to 64", "climate.rm_entry", "alpha/climate/entry/target/set", "10", 64.0),
        ("garbage ignored", "climate.rm_entry", "alpha/climate/entry/target/set", "warm", None),
        ("unlabelled entity ignored", "climate.rm_alpha_bed", "alpha/climate/entry/target/set", "70", None),
        ("label/floor mismatch ignored", "climate.rm_beta_wrongunit", "alpha/climate/entry/target/set", "70", None),
        ("Meta-floor entity ignored", "climate.rm_virtual", "alpha/climate/entry/target/set", "70", None),
        ("wrong topic ignored", "climate.rm_entry", "alpha/climate/bedroom/target/set", "70", None),
    ]:
        inputs = dict(base_inputs, climate_entity=rm)
        ctx = run_vars(env, bp["variables"], inputs,
                       {"trigger": {"id": "cmd", "topic": topic, "payload": payload}})
        ok = all(render(env, c["value_template"], ctx) is True
                 for c in cmd["sequence"] if c.get("condition") == "template")
        got = None
        if ok:
            call = next(a for a in cmd["sequence"] if a.get("action"))
            got = render(env, call["data"]["temperature"], ctx)
        check(f"climate command {label}", got == expect)


if __name__ == "__main__":
    test_syntax_and_exposed()
    test_bridge()
    test_payloads()
    test_climate()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED:")
        for x in FAILS:
            print("  -", x)
        sys.exit(1)
    print("all rendered-template checks passed")
