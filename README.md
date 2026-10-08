# roofz-watcher

Checks roofz.eu every minute (GitHub Actions) and sends a push notification via ntfy
when a new Amsterdam rental appears (cold rent < €1,500, ≥ 30 m²) or when a watched
listing changes status. Filters are at the top of `watch.py`.
