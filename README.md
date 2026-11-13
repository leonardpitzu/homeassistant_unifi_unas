# UniFi Drive / UNAS for Home Assistant

A custom [Home Assistant](https://www.home-assistant.io/) integration for **local
monitoring of UniFi Drive / UNAS storage systems**. It talks directly to the
device on your LAN over the UniFi Drive HTTP API - no Ubiquiti cloud account,
no remote polling.

This is a personal fork of [memphi2/ha-unifi-drive](https://github.com/memphi2/ha-unifi-drive),
maintained for my own UNAS 4. It keeps the `unifi_unas` domain and the entity
unique IDs, so it is a drop-in replacement: entity IDs, history, dashboards and
automations carry over.

## 1.0: lean rewrite

Version 1.0 is a rewrite focused on being cheap to run and easy to read.

| | 0.8.x | 1.0 |
|---|---|---|
| Integration code | ~15,100 lines | ~1,650 lines |
| HTTP requests per poll | 3 (+3 every 10 min) | 4, in parallel |
| Default poll interval | 30 s | 60 s |
| Entities (UNAS 4, 4 HDD + 2 SSD cache, API key, Wake-on-LAN) | 92 | 61 |
| Recorder rows per day (UNAS 4, measured) | ~85,000 | ~7,000 |
| Long-term statistics series | 54 | 14 |

What changed:

- **Parse once per poll.** The four API documents are parsed into one immutable
  snapshot; entities only read precomputed fields. The old code walked the raw
  payload with fuzzy key matching for every entity on every state write.
- **No attribute churn.** 0.8 copied the per-drive SMART metadata, including
  Seagate's raw `read_error_rate` (a counter that changes on every read), into
  the attributes of all eight sensors of each drive. Every poll therefore wrote
  a new state row *and* a new attribute row for every HDD entity, which was
  ~85% of this integration's database writes. Attributes are now static and
  only on the status sensors.
- **Statistics only where a trend matters.** Counts, capacities, sectors,
  progress and power-on hours no longer have a `state_class`. CPU temperature,
  CPU % and memory % are whole numbers (tenths changed on every poll).
- **Correct throughput.** Read / write throughput are the NAS network transmit /
  receive rates from `systems/network-io`. 0.8's fuzzy search sometimes picked
  the SSD cache's `writeKBPS` instead.
- **Removed:** snapshot controls, backup-task polling, firmware `update`
  entities, zeroconf discovery, the custom services, and the duplicate or
  always-empty entities listed under [Upgrading from 0.x](#upgrading-from-0x).

## Requirements

- Home Assistant **2026.8.0** or newer.
- A UniFi Drive / UNAS device reachable on the local network.
- A UniFi **API key** or a local UniFi OS account.

| Credential | Monitoring | Fan profile | Restart / shut down |
|---|---|---|---|
| API key | yes | read-only sensor | not created |
| Local admin account | yes | select (change it) | buttons |

An API key is all monitoring needs. Its writes are not usable: the Drive UI
changes the fan with the same `PUT systems/fan-control {"profile": ...}` this
integration sends, but with a logged-in session; the same request with an API
key fails with HTTP 500. Restart and shut down are UniFi OS console actions that
need the `edit:os-settings:restart` / `poweroff` permission of a local admin.
Controls the configured credentials cannot use are therefore not created, and
leftovers are removed when credentials change. Fan writes and power actions with
a local account have not been tested against a live device.

## Supported devices

| Device | Firmware | Evidence |
|--------|----------|----------|
| UNAS 4 (UNAS4W) | UniFi OS `6.0.18`, Drive `4.4.30` | primary target; test fixtures are a sanitized capture |
| UNAS 2 | UniFi OS `5.1.x` | inherited from upstream, same Drive API |
| Other UniFi Drive / UNAS models | unknown | expected to work where the Drive v2 API matches |

## Installation

### HACS custom repository

1. Open HACS.
2. Three-dot menu -> **Custom repositories**.
3. Add `https://github.com/leonardpitzu/homeassistant_unifi_unas` as category **Integration**.
4. Install **UniFi Drive / UNAS**, then restart Home Assistant.

### Manual

Copy `custom_components/unifi_unas/` into `/config/custom_components/` and restart
Home Assistant.

## Setup

**Settings -> Devices & services -> Add integration -> UniFi Drive / UNAS.**

| Field | Notes |
|-------|-------|
| Host | IP address or DNS name. |
| Port | `443` with HTTPS, `80` without. |
| Use HTTPS / Verify certificate | Match your console; UniFi uses a self-signed certificate by default. |
| API key | Local UniFi API key. |
| Username / password | Local admin account. Used instead of the API key when both are given; adds the fan select and power buttons. |

The device is identified by its MAC address.

**Reconfigure** (integration entry -> three-dot menu) changes the connection and
the credentials without removing the device or its history:

- API key: leave empty to keep the current one, or enter a new one.
- Username: prefilled; clear it to remove the local account.
- Password: leave empty to keep the current one.

Adding or removing a local account reloads the entry and swaps the fan sensor
for the fan select (and adds / removes the restart and shut down buttons), so
point dashboard cards at the new entity. **Reauthenticate** appears on its own
when the stored credentials stop working.

## Options

| Option | Default | Purpose |
|--------|---------|---------|
| Polling interval | 60 s | 30 - 3600 s. |
| Wake-on-LAN MAC address | empty | Adds a **Start** button. Leave empty to disable. |
| Wake-on-LAN broadcast address / port | `255.255.255.255` / `9` | Where the magic packet is sent. |

## Entities

Statistics column: `yes` means the sensor has a `state_class` and keeps
long-term statistics.

**Device**

| Entity | Unit | Statistics |
|---|---|---|
| Overall status (`healthy` / `degraded`) | | |
| At-risk disk count (all drives, including cache SSDs) | | |
| Average disk temperature (pool drives) | °C | yes |
| Cache status | | |
| SSD wear (average of `100 - lifeSpan`) | % | yes |
| Storage usage | % | yes |
| CPU temperature | °C | yes |
| CPU usage | % | yes |
| Memory usage | % | yes |
| Uptime (`3d 7h`) | | |
| Read / write throughput | MB/s | yes |

**Per pool:** status (attribute `raw_status`), at-risk drive count, rebuild
progress, capacity, used, available.

**Per drive** (pool members and cache SSDs): status (attributes `raw_health`,
`media_type`, `model`, `firmware`), temperature (statistics), power-on hours,
capacity, bad sectors, uncorrectable sectors, and remaining life for drives that
report it (SSDs).

**Binary sensors:** device connection (stays available, reports `off` when the
NAS is unreachable), storage problem (any pool or the cache degraded, or any
drive at risk), per pool problem.

**Fan profile:** read-only sensor (`Quiet` / `Balance` / `Cooling`) with an API
key, a select with a local account.

**Controls:** restart and shut down buttons (local account only), Wake-on-LAN
**Start** button when a MAC is configured (any credentials). With Wake-on-LAN
set, the integration also loads while the NAS is off so the button is there.

A single failed poll keeps the last data; from the second consecutive failure
entities go unavailable and the connection sensor turns `off`.

## Upgrading from 0.x

The config entry migrates automatically on first start (entry version 1 -> 2):

- Discovery, snapshot and feature-flag keys are dropped from the entry.
- A stored 30 s interval (the old default) falls back to the new 60 s default;
  any other interval is kept. Wake-on-LAN settings are kept if it was enabled.
- Registry entries for removed entities are deleted:
  - total / used / available storage (use the pool sensors),
  - pool count, degraded pool count, maintenance pool count,
  - system IP, system status, UniFi OS version, Drive version (the versions are
    on the device page as `firmware / Drive app`),
  - maintenance active (device and per pool), pool RAID level, pool drive
    count, pool sync progress, pool average drive temperature, pool usage,
  - per-drive model (now an attribute of the drive status sensor),
  - HDD remaining life (HDDs never report it),
  - firmware update entities, snapshot and backup entities.
- The `unifi_unas.*` services are gone. Use `button.press` on the restart /
  shut down / Start buttons and `select.select_option` on the fan profile.

Existing history of the removed entities stays in the recorder until it ages
out, or remove it with `recorder.purge_entities`.

## Automation example

```yaml
automation:
  - alias: UNAS storage problem
    triggers:
      - trigger: state
        entity_id: binary_sensor.unifi_drive_storage_problem
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "UNAS storage problem - check the NAS."
```

## Diagnostics and privacy

Downloaded diagnostics contain the entry (credentials and host redacted) and the
last raw API responses with serials, MAC and IP addresses redacted. That is
usually all that is needed to support a new firmware's payload.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Setup cannot connect | Host, port and HTTPS settings, reachable from the Home Assistant host. |
| Authentication fails | API key validity, or the local account's permissions. |
| No fan select / power buttons | Expected with an API key; add a local admin account via **Reconfigure**. |
| Restart / shut down fails | The local account lacks the console restart / power-off permission. |
| CPU / uptime sensors empty | The device must expose `systems/device-info` (Drive 4.x). |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt
ruff check .
mypy
pytest tests/ -q --cov=custom_components/unifi_unas
```

CI runs the same gates plus HACS and hassfest validation on every push to
`master`. The test toolchain is pinned in `requirements_test.txt`.

## Legal notes

This is an unofficial community integration. It does not claim affiliation,
sponsorship, authorization, approval, or endorsement by Ubiquiti Inc., Home
Assistant, HACS, or their respective owners.

Product names such as UniFi, UniFi Drive, UniFi OS, Ubiquiti and UNAS are used
only as descriptive compatibility references. The repository does not include
official Ubiquiti logos, copied vendor web assets, or proprietary Ubiquiti source
code. Protocol and endpoint notes document observed interoperability behaviour
only.

## Credits

- [memphi2/ha-unifi-drive](https://github.com/memphi2/ha-unifi-drive) - the
  upstream integration this fork is based on, including the original endpoint
  research.

## License

MIT - see [LICENSE](LICENSE). The upstream copyright notice is retained, as
required.
