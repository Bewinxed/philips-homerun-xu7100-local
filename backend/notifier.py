"""Notifications through Home Assistant: to whoever is home.

Inside the Home Assistant app the Supervisor provides SUPERVISOR_TOKEN and the
Core API at http://supervisor/core/api. Elsewhere set HA_URL and HA_TOKEN (a
long-lived access token); without either, notifications are only logged.

Who gets it: every person.* that is home, or everyone when nobody is. A person's
phone is found through their device trackers: the tracker's device in the
device registry is the Companion app, whose notify action is
notify.mobile_app_<device name, slugified>. NOTIFY_TARGETS overrides that per
person ("person.coen=notify.mobile_app_pixel,person.rebecca=notify.x").
"""
from __future__ import annotations

import json
import os
import time

import requests


def _container_env(name):
    """A container variable. The HA base images start the app through s6-overlay
    with a reset environment and keep the container's variables as files."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        with open(f"/run/s6/container_environment/{name}") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _api():
    token = _container_env("SUPERVISOR_TOKEN")
    if token:
        return "http://supervisor/core/api", token
    if os.environ.get("HA_URL") and os.environ.get("HA_TOKEN"):
        return os.environ["HA_URL"].rstrip("/") + "/api", os.environ["HA_TOKEN"]
    return None, None


class Notifier:
    def __init__(self, overrides: str | None = None):
        self.base, self.token = _api()
        self.overrides = {}
        for part in (overrides or os.environ.get("NOTIFY_TARGETS") or "").split(","):
            if "=" in part:
                person, svc = (s.strip() for s in part.split("=", 1))
                self.overrides[person] = svc.removeprefix("notify.")

    @property
    def available(self) -> bool:
        return bool(self.base)

    def _req(self, method, path, body=None):
        r = requests.request(method, self.base + path, timeout=15,
                             headers={"Authorization": f"Bearer {self.token}",
                                      "Content-Type": "application/json"},
                             data=json.dumps(body) if body is not None else None)
        r.raise_for_status()
        if not r.text:
            return None
        # /api/template answers with plain text, the rest with JSON
        return r.json() if r.headers.get("Content-Type", "").startswith("application/json") else r.text.strip()

    def _notify_services(self) -> set[str]:
        for d in self._req("GET", "/services") or []:
            if d.get("domain") == "notify":
                return set(d.get("services", {}))
        return set()

    def _phone_services(self, person_state: dict, services: set[str]) -> list[str]:
        """A person's Companion app notify actions: the override, else the app
        device behind one of their trackers, else app devices named after them."""
        pid = person_state["entity_id"]
        if pid in self.overrides:
            return [self.overrides[pid]]
        for tracker in person_state.get("attributes", {}).get("device_trackers", []):
            name = self._req("POST", "/template", {"template": (
                f"{{% set d = device_id('{tracker}') %}}"
                "{{ (device_attr(d, 'name') | slugify) if d else '' }}")})
            if name and f"mobile_app_{name}" in services:
                return [f"mobile_app_{name}"]
        # e.g. person.coen -> mobile_app_samsung_sm_g981b_coen, mobile_app_ipad_van_coen
        first = (person_state.get("attributes", {}).get("friendly_name") or pid.split(".", 1)[1])
        token = self._req("POST", "/template", {"template": f"{{{{ {json.dumps(first.split()[0])} | slugify }}}}"})
        return sorted(s for s in services
                      if s.startswith("mobile_app_") and token and token in s.split("_"))

    def recipients(self) -> list[tuple[str, str]]:
        """[(person name, notify service)] for the people who should hear it."""
        states = [s for s in self._req("GET", "/states") or [] if s["entity_id"].startswith("person.")]
        home = [s for s in states if s.get("state") == "home"] or states
        services = self._notify_services()
        out = []
        for s in home:
            name = s.get("attributes", {}).get("friendly_name", s["entity_id"])
            out += [(name, svc) for svc in self._phone_services(s, services)]
        return out

    def send(self, title: str, message: str, tag: str = "homerun") -> list[str]:
        """Notify; returns who was reached. Always leaves a persistent notification."""
        print(f"[notify] {title}: {message}", flush=True)
        if not self.available:
            return []
        reached = []
        try:
            for name, svc in self.recipients():
                try:
                    self._req("POST", f"/services/notify/{svc}", {
                        "title": title, "message": message,
                        "data": {"tag": tag, "priority": "high", "ttl": 0}})
                    reached.append(name)
                except requests.RequestException as e:
                    print(f"[notify] {svc} failed: {e}", flush=True)
            self._req("POST", "/services/persistent_notification/create", {
                "title": title, "message": message, "notification_id": f"{tag}_{int(time.time())}"})
        except requests.RequestException as e:
            print(f"[notify] Home Assistant API failed: {e}", flush=True)
        return reached
