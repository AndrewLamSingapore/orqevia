# Retired application entrypoint - 6 November 2026

The old standalone server and runtime manifest are historical, non-executable
data here. The supported services start app.production_entry:app and
app.interface_server:app. Source import and launch-reference inspection found
no current application, deployment or CI caller of the old entrypoint. The one
remaining security regression imports the retained pure parser in memory_text.
Original database files are retained; this retirement does not open, migrate,
truncate or delete them. Historical bytes and their hashes are in CUSTODY.json.
