# Configuration reference

This page is generated from the code (`mia docs-config --write`), so it cannot go stale. Secrets (passwords, keys) never live in these files, only in the env file; the configuration names the variables. Unknown keys are errors.

German version: config-reference.de.md

## config.yaml


### City (`city`)

| Key | Type | Default | Description |
|---|---|---|---|
| `city.name` | text | **required** | City; appended to partial addresses so they can be found. |

### Search criteria (`criteria`)

| Key | Type | Default | Description |
|---|---|---|---|
| `criteria.max_warm_rent_eur` | integer, > 0 | **required** | Highest warm rent per month in euro; dearer flats are rejected. |
| `criteria.max_cold_rent_eur` | integer, > 0 | **required** | Highest cold rent per month in euro; must not exceed the warm rent. |
| `criteria.min_area_m2` | integer, > 0 | **required** | Minimum living area in square metres. |
| `criteria.min_rooms` | number, > 0 | **required** | Minimum number of rooms (halves allowed, e.g. 2.5). |
| `criteria.move_in.ideal_from` | date (YYYY-MM-DD) | **required** | Preferred move-in date. |
| `criteria.move_in.latest` | date (YYYY-MM-DD) | **required** | Latest acceptable move-in; later flats are rejected. |
| `criteria.move_in.early_flex_days` | integer, ≥ 0 | `0` | Days before the preferred date that still pass (flagged, lower score). |
| `criteria.exclude_keywords` | list (text) | [] | Whole words that exclude a flat (e.g. WBS, Tausch). Negations such as "kein WBS" are recognised. |
| `criteria.min_lease_months` | integer, ≥ 0 | **required** | Minimum lease length in months; shorter or unknown end (sublets) is rejected. |
| `criteria.nice_to_have` | list (text) | [] | Nice-to-haves (balcony, parking); they raise the score and never exclude. |
| `criteria.area.center` | text | unset | Optional: address or station counted as the middle (reference point for the radius). |
| `criteria.area.max_km` | number, > 0 | unset | Optional: largest straight-line distance to the centre in km; needs `center`. An unknown location goes to review, never to reject. |
| `criteria.area.include_postal_codes` | list (text) | [] | Only these postcodes (prefixes are enough, e.g. 803). Empty means anywhere. |
| `criteria.area.exclude_postal_codes` | list (text) | [] | Never these postcodes (prefixes are enough). |
| `criteria.area.exclude_districts` | list (text) | [] | Never these districts (text match, case does not matter). |
| `criteria.station.max_walk_minutes` | integer, > 0 | unset | Optional: longest walk to the nearest stop in minutes (an estimate from the straight line). |
| `criteria.station.kinds` | list (subway | rail | tram | bus) | subway, rail, tram | Which stops count: subway, rail (S-Bahn/rail), tram, bus. |
| `criteria.station.required` | yes/no | no | Yes: a longer walk rejects the flat. No: only the score uses it (weight `scoring.weights.station`). |
| `criteria.station.walking_speed_kmh` | number, > 0 | `4.8` | Walking speed for the estimate in km/h. |
| `criteria.station.detour_factor` | number, ≥ 1 | `1.3` | Detour factor: streets are longer than the straight line (at least 1). |

### Commute (`commute`)

| Key | Type | Default | Description |
|---|---|---|---|
| `commute.targets[].name` | text | **required** | Short unique name of the place, e.g. work. |
| `commute.targets[].destination` | text | **required** | Address or station as a route planner would find it. |
| `commute.targets[].arrival_time` | text | **required** | Arrival time on a weekday morning (HH:MM). |
| `commute.targets[].max_pt_minutes` | integer, > 0 | unset | Longest trip by public transport in minutes (optional; at least one limit is required). |
| `commute.targets[].max_car_minutes` | integer, > 0 | unset | Longest trip by car in minutes (optional). |
| `commute.targets[].modes` | any | all | `any` | `any`: one mode within its limit is enough; `all`: every listed mode must pass. |
| `commute.combine` | all | any | `all` | `all`: every place must pass; `any`: one is enough. |
| `commute.borderline_margin_minutes` | integer, ≥ 0 | **required** | Minutes of tolerance: borderline cases with an estimated address go to review instead of reject. |
| `commute.pt_router` | mvg | motis | **required** | Public-transport router: `motis` (all of Germany) or `mvg` (Munich only, not built yet). |
| `commute.car_router` | google_routes | **required** | Car router; currently only `google_routes`. |
| `commute.motis_base_url` | text | unset | Optional: your own MOTIS server; the default is the community Transitous instance. |
| `commute.car_api_key_env` | text | `GOOGLE_ROUTES_API_KEY` | Name of the environment variable holding the Google Routes key (only needed for a car limit). |

### Sending policy (`send_policy`)

| Key | Type | Default | Description |
|---|---|---|---|
| `send_policy.enabled` | yes/no | no | Master switch for automatic sending. Off: nothing goes out on its own. |
| `send_policy.mode` | shadow | live | `shadow` | `shadow`: only log what would be sent; `live`: really send. |
| `send_policy.min_score` | integer, ≥ 0, ≤ 100 | **required** | Minimum score (0 to 100) for automatic sending. |
| `send_policy.loosen.step_points` | integer, > 0 | **required** | Points the threshold drops per step. |
| `send_policy.loosen.every_days` | integer, > 0 | **required** | Every this many days the threshold drops one step. |
| `send_policy.loosen.floor` | integer, ≥ 0, ≤ 100 | **required** | Floor of the threshold; must not exceed `min_score`. |
| `send_policy.daily_cap` | integer, ≥ 0 | **required** | Maximum automatic sends per day. |
| `send_policy.per_platform_daily_cap` | integer, ≥ 0 | **required** | Maximum per platform per day; not above `daily_cap`. |
| `send_policy.platform_allow_list` | list (text) | [] | Platforms allowed to send automatically. Required for `live`. |
| `send_policy.quiet_hours` | text | unset | Optional: quiet period `HH:MM-HH:MM` (Berlin time) in which nothing is sent. |
| `send_policy.kill_switch_file` | path | **required** | If this file exists nothing is sent (`mia kill` creates it). Not editable in the dashboard. |

### Opening sentence (LLM) (`llm`)

| Key | Type | Default | Description |
|---|---|---|---|
| `llm.base_url` | text | **required** | OpenAI-compatible endpoint for the short, listing-specific opening sentence. |
| `llm.api_key_env` | text | **required** | Name of the environment variable holding the key. |
| `llm.timeout_seconds` | number, > 0 | **required** | On timeout the fixed template text is used. |
| `llm.log_answering_model` | yes/no | yes | Yes: the answering model is noted in the audit trail. |

### Notifications (`notifications`)

| Key | Type | Default | Description |
|---|---|---|---|
| `notifications.channel` | ntfy | telegram | **required** | Notification channel: `ntfy` or `telegram` (Telegram not built yet). |
| `notifications.topic_env` | text | **required** | Name of the environment variable with the ntfy topic URL (acts like a password). |
| `notifications.heartbeat_hours` | integer, > 0 | **required** | A heartbeat arrives every this many hours. |
| `notifications.silence_alert_hours` | integer, > 0 | `48` | Optional: warning when no listing was read for this long (default 48). |

### Storage (`storage`)

| Key | Type | Default | Description |
|---|---|---|---|
| `storage.db_path` | path | **required** | Path of the SQLite database. Not editable in the dashboard. |

### Reply inbox (`replies`)

| Key | Type | Default | Description |
|---|---|---|---|
| `replies.imap_host` | text | **required** | IMAP server of the inbox that receives landlord replies. |
| `replies.imap_port` | integer | `993` | IMAP port (default 993). |
| `replies.folder` | text | `INBOX` | Folder (default INBOX). |
| `replies.username_env` | text | **required** | Name of the environment variable with the username. |
| `replies.password_env` | text | **required** | Name of the environment variable with the password. |
| `replies.lookback_days` | integer, > 0 | `30` | How many days back replies are searched. |

### Alert inbox (`alerts`)

| Key | Type | Default | Description |
|---|---|---|---|
| `alerts.imap_host` | text | **required** | IMAP server of the inbox with the portal saved-search alerts. |
| `alerts.imap_port` | integer | `993` | IMAP port (default 993). |
| `alerts.folder` | text | `INBOX` | Folder (default INBOX). |
| `alerts.username_env` | text | **required** | Name of the environment variable with the username. |
| `alerts.password_env` | text | **required** | Name of the environment variable with the password. |
| `alerts.lookback_days` | integer, > 0 | `3` | How many days back are read (default 3). |
| `alerts.sender_domains` | list (text) | **required** | Only mail from these sender domains is read; required. |

### Sending (SMTP) (`smtp`)

| Key | Type | Default | Description |
|---|---|---|---|
| `smtp.host` | text | **required** | SMTP server for sending. |
| `smtp.port` | integer | `587` | SMTP port (default 587, STARTTLS). |
| `smtp.username_env` | text | **required** | Name of the environment variable with the username. |
| `smtp.password_env` | text | **required** | Name of the environment variable with the password. |
| `smtp.from_address` | text | **required** | Sender address of the messages. |

### Local reply model (`reply_llm`)

| Key | Type | Default | Description |
|---|---|---|---|
| `reply_llm.enabled` | yes/no | no | Yes: a local model reads replies the rules cannot place. |
| `reply_llm.base_url` | text | `http://localhost:11434/v1` | Only this machine or a private network is allowed (replies are private correspondence). |
| `reply_llm.model` | text | `llama3.1` | Model name on the local server. |
| `reply_llm.timeout_seconds` | number, > 0 | `20` | Time limit per request in seconds. |
| `reply_llm.api_key_env` | text | unset | Optional: name of the environment variable with a key for the local server. |

### Automatic reply (`auto_reply`)

| Key | Type | Default | Description |
|---|---|---|---|
| `auto_reply.enabled` | yes/no | no | Yes: viewing offers are answered automatically. Off by default. |
| `auto_reply.mode` | shadow | live | `shadow` | `shadow`: only log; `live`: really answer. |
| `auto_reply.daily_cap` | integer, ≥ 0 | `5` | Maximum automatic replies per day. |
| `auto_reply.max_replies_per_thread` | integer, ≥ 1 | `1` | Maximum per conversation (default 1). |
| `auto_reply.horizon_days` | integer, > 0 | `21` | Slots further away are ignored (default 21). |

### Scoring (`scoring`)

| Key | Type | Default | Description |
|---|---|---|---|
| `scoring.version` | text | `1` | Version label of the scoring; stored in the audit trail. |
| `scoring.weights.commute` | number, ≥ 0 | `25` | Weight of the commute in the score. |
| `scoring.weights.price` | number, ≥ 0 | `20` | Weight of the price. |
| `scoring.weights.size` | number, ≥ 0 | `10` | Weight of the size. |
| `scoring.weights.move_in` | number, ≥ 0 | `15` | Weight of the move-in date. |
| `scoring.weights.balcony` | number, ≥ 0 | `5` | Weight of a balcony. |
| `scoring.weights.parking` | number, ≥ 0 | `3` | Weight of parking. |
| `scoring.weights.private_landlord` | number, ≥ 0 | `7` | Weight of a private landlord. |
| `scoring.weights.freshness` | number, ≥ 0 | `10` | Weight of freshness (listings minutes after publication). |
| `scoring.weights.completeness` | number, ≥ 0 | `5` | Weight of how complete the details are. |
| `scoring.weights.station` | number, ≥ 0 | `0` | Weight of the walk to a stop; 0 means no effect (default). |

## profile.yaml


### Applicants (`applicants`)

| Key | Type | Default | Description |
|---|---|---|---|
| `applicants[].first_name` | text | **required** | First name. |
| `applicants[].last_name` | text | **required** | Last name. |
| `applicants[].age` | integer | unset | Optional: age; stated in the message. |

### Contact (`contact`)

| Key | Type | Default | Description |
|---|---|---|---|
| `contact.phone` | text | **required** | Phone number landlords can call (required). |
| `contact.sender_email` | text | `` | Optional: sender address. |

### Facts for messages (`facts`)

| Key | Type | Default | Description |
|---|---|---|---|
| `facts[].id` | text | **required** | Short unique name of the fact. |
| `facts[].de` | text | **required** | German wording; only facts listed here may appear in a message. |
| `facts[].en` | text | **required** | English wording. |
| `facts[].usage` | always | if_relevant | on_request | **required** | `always`: always state; `if_relevant`: only when the listing has a keyword; `on_request`: only offered on request. |
| `facts[].relevant_if` | list (text) | [] | Keywords for `if_relevant`. |

### Viewing (`viewing`)

| Key | Type | Default | Description |
|---|---|---|---|
| `viewing.de` | text | **required** | Viewing times in German, completing "Besichtigungen sind bei uns … möglich". |
| `viewing.en` | text | **required** | Viewing times in English. |

### Move-in (`move_in`)

| Key | Type | Default | Description |
|---|---|---|---|
| `move_in.earliest` | date (YYYY-MM-DD) | **required** | Earliest move-in as stated in the message. |
| `move_in.latest` | date (YYYY-MM-DD) | **required** | Latest move-in as stated in the message. |
| `move_in.reason` | text | `` | Optional: reason for the move. |

### Availability (`availability`)

| Key | Type | Default | Description |
|---|---|---|---|
| `availability.windows[].days` | list (mon | tue | wed | thu | fri | sat | sun) | **required** | Weekdays: mon, tue, wed, thu, fri, sat, sun. |
| `availability.windows[].start` | text | **required** | Start of the window (HH:MM). |
| `availability.windows[].end` | text | **required** | End of the window (HH:MM). |
| `availability.viewing_minutes` | integer, > 0 | `30` | Length of a viewing in minutes. |
| `availability.min_notice_hours` | integer, ≥ 0 | `12` | Minimum notice in hours. |
| `availability.blackout_dates` | list (date (YYYY-MM-DD)) | [] | Days on which no viewing is possible. |

## Presets

Starting values for `mia init --city <city> --household <household>` and the browser setup. They are example values to adjust, not market data.

| City | key |
|---|---|
| Berlin | `berlin` |
| Hamburg | `hamburg` |
| Munich | `muenchen` |
| Cologne | `koeln` |
| Frankfurt am Main | `frankfurt` |
| Stuttgart | `stuttgart` |
| Düsseldorf | `duesseldorf` |
| Leipzig | `leipzig` |
| Dortmund | `dortmund` |
| Essen | `essen` |

| Household | key | Starting values |
|---|---|---|
| Single | `single` | 1 person, from 1 room(s) and 28 m², minimum lease 24 months |
| Couple | `couple` | 2 persons, from 2 room(s) and 45 m², minimum lease 24 months |
| Family | `family` | 2 persons, from 3 room(s) and 65 m², minimum lease 24 months |
| Student or trainee | `student` | 1 person, from 1 room(s) and 14 m², minimum lease 12 months, shared flats allowed |
