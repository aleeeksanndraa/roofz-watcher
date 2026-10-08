"""Roofz watcher: push-notifies new Amsterdam rentals and status changes via ntfy.sh."""
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

API = ("https://www.roofz.eu/api/ms/listing/properties"
       "?perPage=100&page=1&sort=-published_at&filter%5Bimport_type%5D=RentResident")
LISTING_URL = "https://www.roofz.eu/huur/woningen/{slug}"
STATE = Path(__file__).with_name("state.json")
HEARTBEAT = Path(__file__).with_name("heartbeat.txt")

CITY = "amsterdam"
MAX_COLD_RENT = 1499      # skip anything at €1,500+ cold rent
MIN_AREA = 30             # m²; studios smaller than this are ignored
FAVOURITE_STREETS = ("spaklerweg", "panamalaan")
WATCH_STATUS_SLUGS = {"panamalaan-269"}  # always report status changes for these

TOPIC = os.environ.get("NTFY_TOPIC", "")


def fetch():
    req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0 (roofz-watcher)",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["data"]


def describe(p):
    a, c, h = p["address"], p["characteristic"], p["handover"]
    is_studio = (c.get("subtype") or "").lower() == "studio"
    kind = "студия" if is_studio else f"{c['layout'].get('number_of_bedrooms') or '?'} спальня"
    title = f"{a['street']} {a['house_number']} — €{h['price']} — {c['living_area']} m²"
    body = (f"{kind}, сервис €{h.get('service_costs') or 0}, район {a.get('district') or '-'}\n"
            f"Статус: {p['status']['label']}. С {p.get('available_at_label') or '?'}")
    return title, body, is_studio


def matches(p):
    a, c, h = p["address"], p["characteristic"], p["handover"]
    if (a.get("location") or "").lower() != CITY:
        return False
    if not h.get("price") or h["price"] > MAX_COLD_RENT:
        return False
    return (c.get("living_area") or 0) >= MIN_AREA


PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


def notify(title, body, url, priority="high", tags="house"):
    print(f"NOTIFY: {title} | {body} | {url}")
    if not TOPIC:
        return
    payload = {"topic": TOPIC, "title": title, "message": body,
               "priority": PRIORITIES[priority], "tags": [tags], "click": url,
               "actions": [{"action": "view", "label": "Открыть", "url": url}]}
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(payload).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30)


def main():
    first_run = not STATE.exists()
    state = json.loads(STATE.read_text()) if not first_run else {}
    listings = fetch()
    new_state = {}

    for p in listings:
        pid, slug, stage = str(p["id"]), p["slug"], p["stage"]
        new_state[pid] = {"slug": slug, "stage": stage}
        url = LISTING_URL.format(slug=slug)
        old = state.get(pid)

        # New listing, or an old one re-listed (back to "available" from another stage)
        relisted = old is not None and old["stage"] != "available" and stage == "available"
        if old is None or relisted:
            if first_run or stage not in ("available", "option") or not matches(p):
                continue
            title, body, is_studio = describe(p)
            fav = any(s in p["address"]["street"].lower() for s in FAVOURITE_STREETS)
            prefix = "🔥 " if fav or not is_studio else "🆕 "
            notify(prefix + title, body + "\nПодавай заявку сразу — first come, first served!",
                   url, priority="urgent" if fav else "high")
        elif old["stage"] != stage and slug in WATCH_STATUS_SLUGS:
            title, body, _ = describe(p)
            notify(f"Статус изменился: {old['stage']} → {stage}", title, url,
                   priority="default", tags="bell")

    for pid, old in state.items():
        if pid not in new_state and old["slug"] in WATCH_STATUS_SLUGS:
            notify("Объявление снято с сайта", old["slug"],
                   LISTING_URL.format(slug=old["slug"]), priority="default", tags="bell")

    if first_run and TOPIC:
        notify("Roofz watcher включён ✅",
               f"Слежу за Амстердамом: до €{MAX_COLD_RENT}, от {MIN_AREA} m². "
               f"Сейчас на сайте {len(listings)} объявлений.",
               "https://www.roofz.eu/huur/woningen?filter=location:amsterdam",
               priority="default", tags="white_check_mark")

    STATE.write_text(json.dumps(new_state, indent=1, sort_keys=True) + "\n")
    heartbeat(listings)


def heartbeat(listings):
    """Quiet daily 'still alive' message around 09:00 Amsterdam time."""
    now = datetime.now(ZoneInfo("Europe/Amsterdam"))
    today = now.date().isoformat()
    if now.hour < 9 or (HEARTBEAT.exists() and HEARTBEAT.read_text().strip() == today):
        return
    ams = [p for p in listings if (p["address"].get("location") or "").lower() == CITY
           and p["stage"] in ("available", "option")]
    notify("Вотчер работает ✅",
           f"Проверяю Roofz каждую минуту. В Амстердаме сейчас {len(ams)} свободных/под опцией.",
           "https://www.roofz.eu/huur/woningen?filter=location:amsterdam",
           priority="low", tags="white_check_mark")
    HEARTBEAT.write_text(today + "\n")


if __name__ == "__main__":
    sys.exit(main())
