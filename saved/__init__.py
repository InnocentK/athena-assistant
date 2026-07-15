"""
saved/ — Saved searches and saved actions (Milestone 18).

A small per-profile persistence layer, mirroring `memory/`. See `manager.py`
for `SavedItemsManager`.

Scope note (v1 / Milestone 18): saved *searches* run as local **file** searches
only (`target: "files"`). There is no web-search backend in this milestone, so
runnable saved web searches are explicitly out of scope. Saved *actions* run a
stored prompt through the existing provider router.
"""
