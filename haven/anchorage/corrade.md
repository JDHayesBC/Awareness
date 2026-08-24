# Corrade — Build Reference (for driving a headless SL avatar over HTTP)

**What this is.** Corrade is a headless, closed‑source Second Life / OpenSim *scripted agent*
(bot) by Wizardry and Steamworks (W&S), written in C#/.NET. It logs a normal SL account into
the grid and exposes almost the entire viewer API as ~300+ text commands. You control it by
sending **key‑value command strings** (or JSON) over one of several transports (HTTP, TCP, UDP,
WebSockets, MQTT, or in‑world LSL IM). It emits **notifications** (events) by HTTP‑POSTing them
to callback URLs you register. There is **no all‑in‑one PDF/manual** — the canonical docs are a
(disorganized) DokuWiki. Primary sources, all under `grimore.org`:

- Landing page: <https://grimore.org/secondlife/scripted_agents/corrade>
- API index: <https://grimore.org/secondlife/scripted_agents/corrade/api>
- Full command list (paginated, 25/page): <https://grimore.org/secondlife/scripted_agents/corrade/api/commands>
- Full notification list: <https://grimore.org/secondlife/scripted_agents/corrade/api/notifications>
- Permissions: <https://grimore.org/secondlife/scripted_agents/corrade/api/permissions>
- Configuration keys: <https://grimore.org/secondlife/scripted_agents/corrade/api/configuration>
- Command tutorial (key‑value encoding): <https://grimore.org/secondlife/scripted_agents/corrade/tutorials/command_tutorial>
- Integrated web‑server tutorial (**our transport**): <https://grimore.org/secondlife/scripted_agents/corrade/tutorials/integrated_web-server>
- Notifications tutorial: <https://grimore.org/secondlife/scripted_agents/corrade/tutorials/notifications>

> **The closest thing to a single‑file reference** is the machine‑readable model
> `corrade_qmin_model.json` (~438 KB), meant to be uploaded into an LLM to prime it for
> generating Corrade scripts: <https://grimore.org/_media/secondlife/scripted_agents/corrade_qmin_model.json>
> It is a *priming payload with embedded theory + URLs*, not human documentation. Worth grabbing
> as a companion artifact, but this file (`corrade.md`) is the human build reference.

Verbatim page captures used to build this doc are saved under
`/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/corrade-research/`
(including full 314‑row command catalog `command_catalog.tsv` and 68‑row
`notification_catalog.tsv`).

---

## 0. The data format (READ FIRST — everything depends on it)

Corrade's native scripting language is **WAS key‑value pairs** ("wasKeyValue"): an
`&`‑separated list of `key=value` pairs, where **each key and each value is individually
percent‑encoded** (URL/`%`-encoding, *not* `+`-encoding). Lists inside a value use **CSV**
(the "wasList" format). Example of a raw command body:

```
command=invite&group=My Group&firstname=Good&password=mypassword&lastname=Day
```

Rules that bite you if you ignore them:

- **Escape each key and value separately, then join with `&` and `=`.** Do NOT url‑encode the
  whole assembled string in one pass — values legitimately contain `&`/`=` and would corrupt the
  pair structure. (In Python: build `"&".join(f"{quote(k)}={quote(v)}" for k,v in pairs)` using
  `urllib.parse.quote`, which does `%`-encoding, matching Corrade. Do **not** use
  `urlencode(..., quote_via=quote_plus)` — Corrade wants `%20`, not `+`, for spaces.)
- When **reading** a returned string, extract the *escaped* value for your key first, then
  unescape only that value. Unescaping the whole response first breaks parsing (a value of
  `Tom%26Jerry` would otherwise split the response).
- **Afterburn / passthrough:** any key Corrade doesn't recognize is passed straight through to
  your callback. Use this to correlate responses (e.g. attach your own `reqid=...`).
- **JSON mode:** Corrade *can* be switched (globally, via Nucleus) to speak JSON instead of
  key‑value. Then commands are JSON objects and CSV values become JSON arrays. This is nicer
  for an external daemon, but it is a **global switch** — once on, Corrade no longer accepts
  key‑value, and any in‑world LSL scripts must also use JSON. Recommendation for our daemon:
  **stay on the default WAS key‑value format** unless you commit fully to JSON everywhere; it's
  well‑trodden and every doc example uses it. (Key‑value ↔ JSON equivalence is documented in the
  command tutorial.)

Every command requires at minimum `command`, `group`, and `password` (see auth below).

---

## 1. Quickstart for our daemon (HTTP round‑trip)

### 1a. Transport — Corrade's integrated HTTP server

Enable it in `Corrade.ini` / config (or via Nucleus). Config block (verbatim from the tutorial):

```xml
<HTTPServer>
    <Enable>1</Enable>
    <!-- The prefixes that the HTTP server should listen on. -->
    <Prefixes>
        <Prefix>http://+:8080/</Prefix>
    </Prefixes>
</HTTPServer>
```

`http://+:8080/` binds all adapters on port 8080; `+` = any IP (restrict to e.g.
`http://127.0.0.1:8080/` to keep it local to the daemon host — recommended for us). HTTPS is
possible but needs .NET/mono `HttpListener` cert binding on the OS (separate W&S tutorials for
Windows and Unix). Note this is a **separate** port from Nucleus (54377).

**Request shape:** HTTP `POST` to `http://<corrade-host>:8080/`, body = the `%`-encoded
key‑value string, `Content-Type: application/x-www-form-urlencoded`. Corrade replies **in the
HTTP response body** with a key‑value result string (synchronous), *and/or* POSTs the same result
to a `callback` URL if you supplied one. Optional gzip/deflate output if you send
`Accept-Encoding` and enabled compression in config.

**Concrete example — get balance** (verbatim POST body from the tutorial):

```
command=getbalance&group=My%20Group&password=mypassword
```

Response body looks like:

```
command=getbalance&balance=0&success=True&group=My%20Group
```

**Minimal Python (our daemon side):**

```python
import urllib.parse, urllib.request

CORRADE = "http://127.0.0.1:8080/"
GROUP = "My Group"
PASSWORD = "mypassword"   # the group password (see auth note — plaintext here, SHA1 in config)

def corrade(**pairs):
    # percent-encode each key & value separately, join with & and =
    body = "&".join(f"{urllib.parse.quote(str(k))}={urllib.parse.quote(str(v))}"
                    for k, v in pairs.items()).encode()
    req = urllib.request.Request(CORRADE, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    # parse response: split on & then =, unescape values individually
    out = {}
    for kv in raw.split("&"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            out[urllib.parse.unquote(k)] = urllib.parse.unquote(v)
    return out

# say "Good day!" in local chat
corrade(command="tell", group=GROUP, password=PASSWORD,
        entity="local", type="Normal", message="Good day!")

# IM an avatar by UUID
corrade(command="tell", group=GROUP, password=PASSWORD,
        entity="avatar", agent="0fe3acf3-1526-4b72-a86d-98694932723b",
        message="Hello there")
```

`success=True|False` in the result tells you Corrade *accepted* the command. **Important:**
`success=True` does **not** guarantee the in‑world effect happened (e.g. a group chat message may
silently not deliver). For anything that matters, subscribe to the matching notification and
confirm the effect. There is no separate API token — **the group + password pair IS the auth**
(see §4).

### 1b. Notifications (events → our daemon's HTTP callback)

Your daemon runs its own HTTP endpoint (e.g. `http://daemon-host:9000/corrade-events`). You
**install** a notification subscription with the `notify` command, pointing Corrade at that URL.
When the event fires, Corrade POSTs a key‑value payload to it.

**Subscribe (set local chat + IM + group chat to our URL):**

```python
corrade(command="notify", group=GROUP, password=PASSWORD,
        action="set",
        type="local,message,group",          # CSV list of notification names
        URL="http://daemon-host:9000/corrade-events",
        callback="http://daemon-host:9000/corrade-events")  # confirmation of the bind
```

- `action`: `add` (append URL to the pool, idempotent — won't dup the same URL),
  `set` (replace all URLs for these types), `update`, `remove`, `list`, `purge`.
- `type`: CSV of notification names (see §5). `tag`: optional CSV label so you can
  `remove` by tag later (recommended pattern: `remove` by tag on daemon start, then `add`).
- **Notifications are NOT persistent across Corrade restarts** — re‑install on every daemon
  start (and ideally re‑assert periodically).

**Payload you receive** — e.g. for `local` chat, someone says "boo" nearby, Corrade POSTs:

```
type=local&message=boo&firstname=Sneaky&lastname=Resident&owner=1ad33407-a792-476d-a5e3-06007c0802bf&item=1ad33407-a792-476d-a5e3-06007c0802bf
```

(Parse it exactly like a command result: split on `&`, unescape each value.) Your endpoint
should return HTTP 200 promptly. The discriminator key is `type` (= the notification name).
Different notification types carry different keys (§5).

---

## 2. Chat / messaging commands

Local chat, group chat, IM to an avatar, and conferences are **all the `tell` command**, keyed
by the `entity` parameter. There is no separate `say` command.

| Command | Verbatim required params | Permission | Notes |
|---|---|---|---|
| `tell` | `group`, `password`, `entity` (+ `message`) | `talk` | `entity` selects the channel. Group chat also needs the group ability `Chat→Join Group Chat`. |
| `notice` | `group`, `password`, `action` | `group` | Send a group notice (optionally with attachment). |

**`tell` verbatim examples (from the API page):**

Local chat (`type` = SL ChatType: `Normal`, `Whisper`, `Shout`; optional `channel`, default 0):
```
command=tell & group=<grp> & password=<pw> & message=Good day! & entity=local & type=Normal
```
Group chat (send to the configured group, or another group via `target`):
```
command=tell & group=<grp> & password=<pw> & entity=group & message=Hello group members! & target=A different group
```
IM to an avatar (by `firstname`+`lastname`, or `agent`=UUID). Optional `dialog`
(SL InstantMessageDialog, e.g. `StartTyping`), `online`, `session`:
```
command=tell & group=<grp> & password=<pw> & entity=avatar & agent=0fe3acf3-1526-4b72-a86d-98694932723b & message=Hi
```
Conference (needs a conference `session` UUID, e.g. from the `conference` command):
```
command=tell & group=<grp> & password=<pw> & entity=conference & session=<session-uuid> & message=Hello!
```
Other `entity` values: `estate` (whole estate), `region` (whole region).

> Gotcha (documented): typing into group chat sometimes silently fails; a follow‑up message
> "unsticks" it. Bind the `group` notification to confirm delivery of anything important.
> On negative channels only `type=Normal` works (Whisper/Shout ignored).

To **receive**: subscribe to `local` (nearby public chat), `message` (IM received),
`group` (group chat), `conference`, `regionsayto`, `objectim`, `typing`. See §5.

---

## 3. Appearance / outfit / attachments

SL distinguishes **wearables** (clothing + body parts: shirt, skin, shape…) from **attachments**
(objects on attach points). `wear` handles wearables; `attach` handles objects; `changeappearance`
swaps a whole outfit folder.

| Command | Verbatim required params | Permission | Notes |
|---|---|---|---|
| `wear` | `group`, `password`, `wearables` | `grooming` | `wearables` = CSV of item names **or inventory paths**. Optional `replace`=`true`/`false`. |
| `attach` | `group`, `password`, `attachments` | `grooming` | `attachments` = CSV of **(attachment‑point, item)** pairs. |
| `detach` | `group`, `password`, `attachments`, `type` | `grooming` | `type`=`path`\|`UUID`\|`slot`. Optional `deanimate`. |
| `changeappearance` | `group`, `password`, `folder` | `grooming` | Wear ALL items in a folder, removing current non‑body‑part items. This is "change outfit". Optional `exclude`,`include`,`deanimate`. |
| `getwearables` | `group`, `password` | `grooming` | Returns CSV of worn wearable types→names. |
| `getwearablespath` | `group`, `password` | `grooming` | Same but full inventory paths. |
| `getattachments` | `group`, `password` | `grooming` | Returns attachment points + worn object names. |
| `attachobject` | `group`, `password`, `item` | `inventory` | Attach an in‑world primitive (not from inventory). |
| `dropobject` | `group`, `password` | `inventory` | Drop an attached object to the ground. |
| `rebake` | `group`, `password` | `grooming` | Force a texture rebake (fix "cloud"/grey avatar). |

**`wear` (verbatim):**
```
command=wear & group=<grp> & password=<pw> & wearables=CSV("/My Inventory/Clothing/Dragon Tattoo")
```
(`replace=true` replaces the item in its slot; `false` adds it.)

**`attach` (verbatim)** — `attachments` is CSV of point,item pairs:
```
command=attach & group=<grp> & password=<pw> &
attachments=CSV("Skull","/My Inventory/Objects/Helmet","Mouth","/My Inventory/Fun Stuff/Milk Bottle")
```
Attachment points (verbatim list): `Default, Chest, Skull, LeftShoulder, RightShoulder, LeftHand,
RightHand, LeftFoot, RightFoot, Spine, Pelvis, Mouth, Chin, LeftEar, RightEar, LeftEyeball,
RightEyeball, Nose, RightUpperArm, RightForearm, LeftUpperArm, LeftForearm, RightHip,
RightUpperLeg, RightLowerLeg, LeftHip, LeftUpperLeg, LeftLowerLeg, Stomach, LeftPec, RightPec,
HUDCenter2, HUDTopRight, HUDTop, HUDTopLeft, HUDCenter, HUDBottomLeft, HUDBottom, HUDBottomRight,
Neck, Root`. (`Default` = right hand if not previously attached; `Root` = avatar center.)

**`detach` (verbatim)** — note `type` is required:
```
command=detach & group=<grp> & password=<pw> & type=path &
attachments=CSV("/My Inventory/My Outfit/Helmet","/My Inventory/Cool Stuff/Milk Bottle")
```

**`changeappearance` (verbatim)** — the outfit‑swap primitive:
```
command=changeappearance & group=<grp> & password=<pw> & folder=/My Inventory/CoolOutfit
```
Caveat (documented): Corrade does **not** support multiple attachments per slot, so outfit
folders must not contain two objects for the same attach point.

**"Become / reload appearance":** there is no single "become" command; the equivalent is
`changeappearance` (swap outfit) + `rebake` (force texture bake). To reload after wearables get
stuck, `rebake`.

---

## 4. Inventory basics (to find items to wear)

The wear/attach/animation commands all accept either an **item name**, an **inventory path**
(e.g. `/My Inventory/Clothing/Dragon Tattoo`), or an **asset/inventory UUID**. To resolve
things, these `inventory` commands help:

| Command | Verbatim required params | Permission | Notes |
|---|---|---|---|
| `inventory` | `group`, `password`, `action` | `inventory` | UNIX‑like inventory nav: `ls`, `cwd`, `cd`, `mkdir`, `rm`, `cp`, `mv`, `ln`, `chmod`. Each group has its own current dir (starts at `My Inventory`). |
| `getinventorypath` | `group`, `password`, `type` | `inventory` | `type=UUID`+`UUID=...` → full path; or `type=pattern`+`pattern=<regex>` (+optional `path`, `options`) → matching paths. |
| `getinventorydata` | `group`, `password`, `item`, `data` | `inventory` | Query fields (CSV in `data`, e.g. `InventoryType,CreatorID`) of an item by path/UUID. |
| `getinventoryoffers` | `group`, `password` | `inventory` | List pending inventory offers. |
| `replytoinventoryoffer` | `group`, `password` | `inventory` | Accept/decline an offer (needs session UUID from the `inventory` notification). |
| `download` / `upload` | `group`, `password`, … | `interact,inventory,system` / `inventory,economy` | Asset transfer to/from the grid. |

**`inventory ls` (verbatim):**
```
command=inventory & group=<grp> & password=<pw> & action=cwd
```
**`getinventorypath` by UUID (verbatim):**
```
command=getinventorypath & group=<grp> & password=<pw> & type=UUID & UUID=95553c51-8285-af6a-ed91-9ac30cf85c79 & callback=<url>
```
Recommended flow for the daemon: build outfit folders in the bot's inventory once, then just call
`changeappearance folder=/My Inventory/<Outfit>`; use `getinventorypath type=pattern` to discover
item paths programmatically when needed.

---

## 5. Movement / posture / animation

| Command | Verbatim required params | Permission | Notes |
|---|---|---|---|
| `teleport` | `group`, `password`, `entity` | `movement` | `entity`=`region`\|`global`\|`landmark`. See below. |
| `walkto` | `group`, `password`, `position` | `movement` | Walk to a local position (preferred over `autopilot`). |
| `flyto` | `group`, `password`, `position` | `movement` | Fly toward a position; `fly` bool sets final flight state. |
| `autopilot` | `group`, `password`, `position`, `action` | `movement` | **Deprecated** — use `walkto`. `action`=`start`\|`stop`. |
| `fly` | `group`, `password`, `action` | `movement` | `action`=`start`\|`stop`\|`get`. |
| `jump` | `group`, `password`, `action` | `movement` | `start`\|`stop`. |
| `crouch` | `group`, `password`, `action` | `movement` | `start`\|`stop`. |
| `nudge` | `group`, `password` | `movement` | Small directional move. |
| `turnto` | `group`, `password` | `movement` | Rotate toward an LSL vector. |
| `sit` | `group`, `password`, `item` | `movement` | Sit on object by name/UUID. Optional `range`, `offset`, `deanimate`. Radar‑bound. |
| `relax` | `group`, `password` | `movement` | Sit on ground. |
| `stand` | `group`, `password` | `movement` | Stand up. Optional `deanimate`. |
| `animation` | `group`, `password`, `item`, `action`, `type` | `grooming` | Start/stop one animation. |
| `batchanimation` | `group`, `password` | `grooming` | Start/stop multiple. |
| `deanimate` | `group`, `password` | `grooming` | Stop all non‑Linden animations. |
| `playgesture` | `group`, `password`, `item` | `grooming` | Trigger a gesture from inventory (name/UUID). |
| `playsound` | `group`, `password`, `item` | `interact` | Play a sound asset. |

**`teleport` (verbatim, region‑by‑name):**
```
command=teleport & group=<grp> & password=<pw> & entity=region & region=<Region Name> & position=<128, 128, 10> & fly=False
```
`entity=global` uses `position=<global vec>`; `entity=landmark` uses `item=<landmark UUID or path>`.
Optional `turnto`, `fly`, `deanimate`. Teleports are subject to region teleport routing (you may
not land exactly on `position`).

**`sit` (verbatim):**
```
command=sit & group=<grp> & password=<pw> & item=Chair & range=5
```
`item` = object name or UUID; `range` (optional) = search sphere in meters; `offset` = sit offset.

**`stand` (verbatim):**
```
command=stand & group=<grp> & password=<pw>
```

**`animation` (verbatim)** — `action`=`start`\|`stop`, `type`=`inventory`\|`UUID`:
```
command=animation & group=<grp> & password=<pw> & action=start & type=inventory & item=/My Inventory/Animations/Dance & callback=<url>
```

**`playgesture` (verbatim):**
```
command=playgesture & group=<grp> & password=<pw> & item=/My Inventory/Animations/Happy Dance
```

**`fly` (verbatim):**
```
command=fly & group=<grp> & password=<pw> & action=start
```

Most movement/pose commands take an optional `deanimate=True|False` to stop active animations
first. `sit`/`local`/radar commands are "radar‑bound" — the object/avatar must be within the
bot's configured `Range` (draw distance, default 64 m).

---

## 6. RLV support

RLV (Restrained Love Viewer) commands exist in Corrade's lineage (there is an `rlv`
**notification** and `RLV` **config** with an enable flag + behaviour blacklist), but per the W&S
FAQ, **RLV is legacy and being phased out**: "It does not make sense to apply RLV to Corrade
because Corrade is a scripted agent and has no self‑asserted agency… It is planned … for RLV
support to be entirely removed from Corrade and then provided as a separate program." The Corrade
command API supersedes RLV's capabilities. **For our use case, do NOT design around RLV** — use
native Corrade commands (`wear`/`detach`/`animation`/`sit`/`teleport`/etc.) instead. If you ever
need it: enable via config `<RLV><Enable>1</Enable></RLV>` and subscribe to the `rlv`
notification; RLV behaviours arrive as chat, not as Corrade commands.
(Config: <https://grimore.org/secondlife/scripted_agents/corrade/api/configuration/rlv/enable>)

---

## 7. Notifications reference

Install with `notify` (§1b). Payloads always include a `type` (= notification name) key plus
type‑specific keys. Complete list has **68 notification types** (full table in
`work/corrade-research/notification_catalog.tsv`). The ones most relevant to a chat/presence/
outfit daemon:

| Notification | Key payload fields (verbatim `data`) | Fires on |
|---|---|---|
| `message` | `type, firstname, lastname, agent, message, language` | **IM received** (private message to the bot). |
| `local` | `type, owner, item, position, message, entity, audible, volume, name, region` | Nearby public/local chat. `entity`=`System`\|`Agent`\|`Object`; `audible`=`Not`\|`Barely`\|`Full` (may have no `message` if `Barely`). |
| `group` | (group chat message fields) | Group chat. Use to confirm `tell entity=group` delivery. |
| `conference` | `notification, firstname, lastname, agent, message, language, name, session, restored` | Conference messages. |
| `regionsayto` | — | Directed region‑say to the bot. |
| `objectim` | — | IM from an object. |
| `typing` | — | Someone start/stop typing. |
| `avatars` | `notification, id, entity, position, rotation, action` (`appear`/`vanish`) | Avatars entering/leaving radar range. |
| `friendship` | — | Friendship offers/status (reply with friendship commands). |
| `inventory` | — | Inventory offers (reply via `replytoinventoryoffer`). |
| `teleport` | — | Teleport lures/offers (reply to accept). |
| `permission` | — | Script permission requests (reply to grant, e.g. to animate/sit). |
| `dialog` | `notification, firstname, lastname, message, channel, name, item, owner, button, id` | Blue‑box script dialogs. Reply via `getscriptdialogs`/`replytoscriptdialog`. |
| `sit` | — | Sit/stand state changes. |
| `animation` | `notification, animation` | Animations starting on the bot. |
| `appearance` | `notification, firstname, lastname, version, COF, region, hover` | Avatar appearance data. |
| `outfit` | — | Outfit changes. |
| `alert` | `notification, message` | Sim/grid alert messages (e.g. restart warnings). |
| `balance` | `notification, balance` | L$ balance changed. |
| `login` / `logindata` | — | Bot login lifecycle. Useful for daemon health. |
| `heartbeat` | — | Periodic keepalive from Corrade. |
| `collision` | `notification, aggressor, magnitude, time, entity, victim` | Something collides with the bot. |
| `region` / `crossing` | — | Region change / region‑cross events. |

**Three‑way handshake pattern** (for anything interactive — accept friendship, click a dialog
button, grant animate permission): (1) install the notification with `notify`; (2) receive the
event, read its fields; (3) send the matching `reply…`/action command using the ids from the
event. The "commands to reply" column on each notification's wiki page names the exact command.

Full notification catalog + per‑type reply commands: see `notification_catalog.tsv` and
<https://grimore.org/secondlife/scripted_agents/corrade/api/notifications>.

---

## 8. Permissions model (ACL) — 14 permission classes

Permissions gate what a **group** may do; they protect the bot from its own configured groups.
Each command's required permission is listed on its wiki page (and in `command_catalog.tsv`).
Grant a group only what it needs.

| Permission | Governs |
|---|---|
| `talk` | Local/group/IM chat (`tell`, `notice`). |
| `grooming` | Appearance/profile: `wear`, `attach`, `detach`, `changeappearance`, `animation`, `playgesture`, `rebake`, `getwearables`, picks, classifieds. |
| `movement` | `teleport`, `walkto`, `fly`, `sit`, `stand`, `jump`, `nudge`, etc. |
| `inventory` | Inventory nav/query, attach in‑world objects, offers, `download`/`upload`. |
| `interact` | Interact with in‑world primitives, `playsound`, avatar key/name resolution. |
| `notifications` | Install notifications via `notify`. **Needed for our event pipeline.** |
| `group` | Group ops: invite, roles, eject, ban, notices. |
| `economy` | Spend L$: pay avatars, buy items, upload fees. |
| `bridge` | Outbound calls (`HTTP`, `MQTT` commands). |
| `land` | Parcel/region land ops. |
| `friendship` | Friend requests/list. |
| `mute` | Mute list. |
| `directory` | Directory search (land/events/people/groups). |
| `database` | Per‑group key‑value store. |
| `system` | **Dangerous** — reconfigure/poll the whole config (`addconfigurationgroup`, etc.). |
| `execute` | **Dangerous** — run OS commands on the host. Leave OFF. |

For our daemon (chat + outfit + movement + events), a group typically needs:
**`talk`, `grooming`, `movement`, `inventory`, `interact`, `notifications`** (add `economy`,
`group`, `friendship` only if used). Never grant `execute`; grant `system` only if the daemon
must reconfigure Corrade at runtime.

---

## 9. Configuration & setup checklist

Corrade is configured either by the **Nucleus** web UI or by editing the config XML
(`CorradeConfiguration.xml`; docs also call the file `Corrade.ini`).

1. **Install / run.** Docker is the canonical method: image
   `wizardrysteamworks/corrade` (<https://hub.docker.com/r/wizardrysteamworks/corrade>);
   Dockerfile + compose under `grimore.org/assets/docker/{build,compose}/corrade`. Native: needs
   the current **.NET runtime** (Linux/macOS) — SDK not required; Windows binary self‑contained.
   Platforms: Windows 10+, Linux x64 / ARM64 (ARMv7+; not Raspberry Pi v1), macOS 10.12+.
   ~100–350 MB RAM. Same firewall ports as a normal SL viewer; extra ports (HTTP server, etc.)
   must be forwarded to the Corrade host.
2. **First boot → Nucleus.** On first start with no config, Corrade launches the **Nucleus**
   web server at **`http://127.0.0.1:54377/`** (or `http://<host>:54377/` remotely; it binds all
   addresses). Log in with default password **`nucleus`** (change later by copying
   `NucleusConfiguration.xml.default` → `NucleusConfiguration.xml` and editing the password).
3. **Login credentials (the SL account the bot logs into).** `Login → Firstname`, `Lastname`,
   `Password`. In the XML: `FirstName`, `LastName`, and `Password` = **unsalted MD5 of the account
   password with `$1$` prepended** (e.g. `$1$<md5hex>`). `LoginURI` defaults to
   `https://login.agni.lindenlab.com/cgi-bin/login.cgi` (main SL grid).
4. **Configure at least one group (this is your API auth).** `Groups → Group → Name` must be a
   **real SL group the bot belongs to**; `Groups → Group → Password` = a **SHA1 hash** of any
   made‑up string (NOT the account password — a distinct per‑group secret). Your daemon sends the
   **group name** as `group=` and the **plaintext** whose SHA1 you stored as `password=` (Corrade
   hashes the incoming value and compares). Also set that group's **`Permissions`** and
   **`Notifications`** collections. A default `[Wizardry and Steamworks]:Support` group ships in the
   sample config — edit or remove it.
5. **Enable the HTTP server** (§1a) and, if remote, forward the port.
6. **Commit** (Nucleus "Commit configuration") and wait for login. If it won't connect, check
   `Logs` in Nucleus; a `login failed : ban` usually means a temporary login throttle — wait a few
   minutes. Resetting: stop bot, delete `CorradeConfiguration.xml`, restart to re‑run first‑boot.
7. **Useful global config keys:** `Range` (draw distance, default 64 m — governs radar‑bound
   commands like `sit`/`local`), `AutoConnect` (default 1), `MultipleSimulatorConnections`
   (region crossings; unreliable), `Language`, `MessageLogging`. Server blocks:
   `HTTPServer`, plus `TCPServer`/`UDPServer`/`WebSocketsServer`/`MQTTServer` if desired.

**"Master avatars":** the concept the task mentions maps in Corrade onto **configured groups +
group password**, not a per‑avatar master list — commands are authorized by the group/password
pair, and *what* a group may do is its permission set. (Individual command pages sometimes also
require in‑world **group abilities**, e.g. group chat needs `Chat→Join Group Chat` on the SL
group role the bot holds.)

---

## 9a. Field notes from the first live bring-up (2026-08-23, Lyra/LyraPattern Resident)

Everything below is *observed on hardware*, not inferred — it corrects or sharpens the theory above.

**Nucleus hides most options behind a "Normal → Advanced" toggle.** The config form opens in a
minimal ("Normal") view. There is a **green button labelled `Normal`** at the top; clicking it
switches to **`Advanced`** and reveals the full surface — the complete **Permissions** grid, the
**Notifications** grid, and the server blocks (`HTTPServer` etc.). If you can't find a setting
(permissions, notification types, the HTTP-server enable), you're in Normal view — flip it to
Advanced. This one toggle gates almost everything you actually need to configure.

**Config changes require a Corrade RESTART — Nucleus "commit/apply" is not enough.** Nucleus writes
`CorradeConfiguration.xml` and live-applies *some* state, but the running process does **not**
hot-reload: (a) server bindings (`HTTPServer` — the `:8080` listener only binds at startup), and
(b) **group permission masks**. Confirmed the hard way: with `land` added via Nucleus and committed,
`getregiondata` kept returning `no Corrade permissions` (status 48467) until `docker restart
corrade-lyra` — after which it worked. **Rule: after any permission or server change, bounce the
container.** (Grant everything in one Nucleus session, *then* one restart.)

**Persistent config = named volume on `/etc/corrade`.** The image symlinks
`/opt/corrade/CorradeConfiguration.xml` (and `NucleusConfiguration.xml`, `Log4Net.config`) →
`/etc/corrade/…`, and declares `/etc/corrade` as its VOLUME. So a named volume mounted there
persists account + groups + permissions + notifications across `docker compose up`/recreate.
Compose file: `haven/anchorage/docker-compose.corrade.yml`. **Bind both ports to `127.0.0.1` only**
(`54377` Nucleus, `8080` HTTP command server) — Nucleus ships with default password `nucleus`, so
never expose it to the LAN; the daemon is the only client and it's co-located.

**Event queue has a login-settle window (this is mostly normal, not a bug).** After each login the
event queue takes ~30 s to a few minutes to come up. Much of that is just SL streaming the region
to a fresh client — the same "wait for the rez-dust to clear" a human viewer has (~30 s typical).
Occasionally there's a transient `Seed capability returned a 404` / `missing caps URI` that tears
the queue down once and it re-establishes on retry (observed: down at login → `Event queue running`
~4 min later, then stable). **While the queue is down:** `getselfdata` *static* fields (`Name`,
`Health`) still resolve, but *live* fields (`SimPosition`, `Velocity`), avatar sight, and
`getregiondata`'s live fields (`AgentCount`) come back empty or `timeout getting parcels`.
**Implication for the daemon/perception layer:** tolerate event-queue-down, and **(re)install
`notify` subscriptions when the queue comes UP** (watch the log for `Event queue running`), not
just once at daemon start.

**`getselfdata` field names that actually work.** Position is **not** `Position` (returns empty) —
use `SimPosition`, `RelativePosition`, `GlobalPosition`. `Velocity` works. `Name`, `Health` resolve
without the event queue; positional/velocity fields need it. Vectors come back like
`"<185.04,+212.94,+29.84>"` (spaces as `+`).

**Sensing verbs — proven live:**
- `getavatarpositions` `entity=region` (perm **`interact`**) → **sight**: CSV of `name, UUID,
  <position>` for every avatar in region. First real use returned Caia, Brandi, and self in a row.
- `getregiondata` `data=Name,Access,AgentCount,…` (perm **`land`**) → region info (`The Anchorage`,
  `Adult`). `AgentCount` needs the event queue; `Name`/`Access` don't.
- `getobjectsdata` `entity=range&range=<m>&data=Name,Position,ID` (perm **`interact`**) → nearby
  objects. **Caveat: most prims report a blank `Name`.** Don't select furniture by name — sort by
  distance from `SimPosition` and pick the nearest (worked cleanly for "the chair nearest me").

**Acting verbs — proven live:**
- `sit` `item=<UUID>` (perm **`movement`**) → sits on an object. Confirm via
  `getselfdata data=SittingOn,SimPosition`: a **non-zero `SittingOn`** (object local-id) plus a
  raised Z = seated. `stand` to get up.
- Reminder (matches the client module): a command's `success=True` means **accepted, not
  effected** — confirm real-world effect via `getselfdata`/the matching notification.

**Notification callbacks — the container→host address matters (Docker Desktop / WSL2).** The
`notify` callback `URL` must be an address the **container** can reach the *host* on — where the
daemon's `/corrade-events` listens. Under Docker Desktop's WSL2 backend the containers run in a
*separate* distro from the daemon, so `127.0.0.1` and the **bridge gateway `172.19.0.x`** do NOT
work (binding the gateway on the host → `Cannot assign requested address`; the container hitting it →
`Connection refused`). What works: **`host.docker.internal`** (Docker Desktop injects it
automatically) — the WSL distro's own `eth0` IP works too. So: advertise the callback as
`http://host.docker.internal:<port>/`, and **the daemon must bind `0.0.0.0`** (not loopback) to be
reachable from it. (Native docker-in-WSL behaves differently — the bridge gateway is bindable there —
so treat the callback host as **config**, not a constant.) Verified live with a throwaway listener:
`host.docker.internal` reached, gateway refused.

**Dialog reply = the closed sensorimotor loop (proven live).** An `llDialog` blue-menu arrives as a
`dialog` notification carrying `id` (the dialog UUID), `channel`, `item`, `owner`, `message`, and
`button` — the buttons as a flat CSV `index,<n>,<label>,<n+1>,<label>,…`. Reply with
`replytoscriptdialog action=reply&dialog=<id>&index=<n>` (or `button=<label>`; `action` also takes
`ignore`/`purge`). AVsitter furniture pattern: **touch** the seat to open the pose menu; `[ADJUST]`
moves the sit target (fixes a "weird sit"), `SINGLE-F*` / other `*`-suffixed buttons open submenus of
named poses (`f-sit1`…), `[BACK]`/`[SWAP]` navigate. First complete loop proven: `touch` → dialog
notification captured → choose → `replytoscriptdialog` → re-`touch` shows the new pose in the header
(`[f-sit1]` → `[f-sit3]`). Sense → decide → act → confirm, end to end.

**Speech — proven live.** `tell entity=local type=Normal message=<text>` (perm `talk`) speaks in
local chat in the bot's *own* voice (not via a relay prim). `success=True`. First real in-world
utterance shipped this way. Percent-encode the message (the client / `--data-urlencode`).

**Subscription masks — a `notify set` is all-or-nothing.** `notify action=set&type=a,b,c` is
**rejected wholesale** if *any* type isn't in the group's **Notifications** mask (Nucleus →
Advanced → the notifications grid). Symptom: `success=False, error=notification not allowed,
data=<the offending type>` and **none** of the batch installs. (Hit live: `wind` wasn't in the mask,
so a `sound,wind,local` set failed entirely; `sound,local` alone succeeded.) So: subscribe only to
types the group actually has enabled, or the whole install silently no-ops.

**Hearing has real edges — environmental sound is NOT reliably audible.** The `sound` notification
fires on **discrete triggered sounds** (`llTriggerSound`/`llPlaySound` *events*). It did **not**
catch a live rain weather-system (0 `sound` events over ~60s across three listens) even though the
region was audibly raining and the builder confirmed it's `llSound()`-based. Best explanation:
environmental rain is a **continuous loop** (an `llLoopSound` set once, and/or "invisible rain roof"
attachment loops) — a loop already playing before you subscribe **never re-fires the trigger event**,
so there's nothing to hear; range/attenuation and attached-object sources compound it. Proven it's
NOT a broken callback: a `dialog` control (touch the chair) came through the *same* callback in the
same window while the rain stayed silent. **Takeaway:** "is it raining / what's the weather" is not a
`sound` question — reach for **sight** (`particles` notification = the raindrops) or the **weather
system's state**, not hearing. (A promising *separate* audio sense: pull the parcel **MusicURL**
(`getparceldata`, perm `land`) and poll the shoutcast stream's "now playing" metadata → know the
room's music. That's a buildable sense; noted for `senses-design.md`.)

**Object NAMES are not free — `getobjectsdata` won't give them (ROOT-CAUSED 2026-08-23).**
A range scan (`getobjectsdata entity=range&data=Name,Position,ID`) returns **blank/absent Name
for every prim** — even ones you've sat on and touched. This is not a bug and not fixable by
waiting: the scan returns only the **fast `ObjectUpdate` cache** (`Position, Text, Scale,
Velocity, LocalID, ParentID` — the stuff that streams for free). `Name`/`Description`/`CreatorID`
live on `Primitive.Properties`, populated by a **separate, slower `ObjectProperties` fetch** the
sim sends only when an object is *selected*. Diagnostic tell: request a mixed field set and watch
what comes back — `Text,,` returns **empty-but-present** (a direct field), while `Name`/`Description`
are **absent entirely** (Properties never fetched). Corrade's docs say it outright: *"the name of
the object is not part of [basic object info]… the command may take a long time to complete."*
- **Fix / correct tool:** `getprimitivepropertiesdata` (perm `interact`; required `item`, optional
  `range`). `item` nominally accepts a **UUID or a name to search for**, but **by-name is slow and
  unreliable — resolve by UUID** (see the ✅ note below). `data` follows the
  [ObjectProperties structure](http://libopenmetaverse.grimore.org/html/T_OpenMetaverse_Primitive_ObjectProperties.htm)
  (`Name, Description, OwnerID, CreatorID, CreationDate, …`). It does the real round-trip, so it's
  slower — keep `range` small.
- **Sight design consequence (→ `senses-design.md`): resolve names in TWO steps, lazily.**
  `getobjectsdata` for the cheap spatial roster (who/what/where, by UUID) → then
  `getprimitivepropertiesdata` **on-demand** for the *one* thing you're reaching for (what you're
  about to sit on, who owns that prim). Don't name-resolve all ~100 prims in range; focus first,
  resolve second. That's both cheaper and the more honest perception model.
- **✅ VALIDATED live (2026-08-23):** `getprimitivepropertiesdata item=<UUID>` resolves
  `Name/Description/OwnerID/CreatorID` fast and reliably (chairs, calling post, poseball all read
  clean). **But by-NAME resolution must not be trusted:** `getprimitivepropertiesdata item="TIS
  Hybrid Home Calling Post" range=12` **timed out** (30s, and again at 90s), and `touch
  item="<name>"` returned **`primitive not found`** — the name search scans `Primitive.Properties`
  that aren't cached. **Reliable pattern is UUID-only:** `getobjectsdata entity=range` → cheap
  roster (UUID+Position) → per-UUID `getprimitivepropertiesdata` for the one thing you're reaching
  for. Never touch/resolve by name in a hot path.

**Region-scoped commands need a live region — cached commands lie during an outage (2026-08-23).**
When the bot loses its SL session (grid login outage, kick, disconnect) it can sit **logged-out but
still answering HTTP**: `getselfdata`/`getobjectsdata`/`getavatarpositions` keep returning **stale
cached** values, so it *looks* alive — but `getselfdata data=SimPosition` reads **`<0,+0,+0>`** and
every region-scoped command (`getregiondata`, `getprimitivesdata`, `getprimitivepropertiesdata`)
returns **`region not found` / `general error`**. **Health check for "am I really in-world":** poll
`SimPosition` (non-zero) — NOT command success. Ground truth is in the container log:
`docker logs corrade-lyra | grep -E "Relogging|Login|Simulators"` — `Simulators: 0` in the
heartbeat = not connected to any sim. Corrade's `MaintainGridConnection` auto-relogs ~every 60s, so
it recovers itself once the grid is back — no restart required.

**Config gotcha — invalid notification enum silently degrades config load.** The persisted
`/etc/corrade/CorradeConfiguration.xml` had `<Notification>logindata</Notification>` — **not a valid
enum** in 14.0.510.37 (valid is `login`). It throws an `XmlSchemaValidationException` on *every*
config load/relogin. It is NOT fatal (the bot ran fine with it present) but it's persistent noise
and should be removed. **Source is a Corrade UI bug:** the Nucleus *Advanced → Notifications*
grid offers a `logindata` checkbox that emits schema-invalid config — untick it **in the UI**
(then it drops from the persisted file on apply), don't hand-edit the XML. Audit the notifications block with
`docker exec corrade-lyra grep -o "<Notification>[a-z]*</Notification>" /etc/corrade/CorradeConfiguration.xml`
against the valid enum list before trusting a notify config.

**Auth model — CONFIRMED (was an assumption in §12).** The daemon sends the **group name** as
`group=` and the **plaintext** group password as `password=`; the config stores its **SHA1**
(`<Password>` in the group block is 40 hex). Corrade hashes the incoming value and compares.
Verified live with `group=Haven`. Note the sample config also ships a leftover **`New Group`** —
harmless, but use your own group.

**The auth "group" does NOT need to be a real in-world SL group (CLARIFIED 2026-08-23).** Corrade
does access-control *per group not per avatar*, but the config `<Group>` name+password is a **local
shared-secret ACL** — it authenticates HTTP commands and gates the config permission/notification
masks. It is **independent of any real grid group**. Proven: the entire embodiment set — move,
sense (`getobjectsdata`/`getprimitivepropertiesdata`), `tell entity=local`, `sit`, `touch`, and a
**dance animation auto-triggering on sit** — all worked against a **made-up group name that does not
exist on the grid** (`Haven`). A real in-world group (bot as a *member* with roles) is required
**only for group-scoped operations**: group chat (`tell entity=group`/`group` notification),
inviting/managing members, role assignment, and land/estate actions done *through* a group (FAQ:
*"most of the checks Corrade performs end up querying group permissions"* — but only for those
operations). **Security guidance:** a config-only credential not bound to any real group is a
*cleaner* posture, not a broken one — no external group can command the bot without the local
password (bound to `127.0.0.1`). **Never** point the auth group at a powerful real group (e.g. the
estate-controlling group) to satisfy the field — that over-privileges the bot. If group features are
ever wanted, join a **dedicated minimal-role throwaway group** and use *its* UUID. The Nucleus/config
"must be an existing group on the grid" copy describes Corrade's *intended* setup; it is **not**
enforced at login or for avatar-level actions.

**The full couples-dance interaction loop — PROVEN END-TO-END (2026-08-23).** First real dance with
Jeff. The complete sense→act chain, now a repeatable recipe:
1. **`touch` the "calling post" (by UUID)** — the touch *itself* fires an `llRequestPermissions`,
   arriving as a **`permission` notification** (NOT an llDialog, and NOT triggered by *sitting* —
   this corrected a wrong assumption that cost a long detour). Fields captured live:
   `firstname/lastname/owner` (requester), `item` (requesting prim UUID), `task` (script UUID),
   `permissions` (`TriggerAnimation`), `id` (internal request UUID), `region`. **Grant it:**
   `replytoscriptpermissionrequest action=reply task=<task> item=<item> permissions=<perms>` →
   `success=True`. Once granted for a `task`, it does **not** re-request that session.
2. **Then it is pure llDialog.** Reply with `replytoscriptdialog action=reply dialog=<id>
   channel=<ch> item=<obj> index=<n>`. **Use `index=`, not `button=`** — zTIS labels carry unicode
   arrows + `||N` encoding suffixes that make text-matching brittle; the index is stable. **Each
   reply spawns a NEW dialog with a NEW `id` (and sometimes a new `channel`** — it changed
   `-412301919`→`-627328191` between menu levels) — capture the fresh `id`/`channel` from every
   dialog notification before replying. **Menus are STATEFUL:** a fresh `touch` returns to wherever
   you left the menu, not the top; navigate up with the **`Up`** button. Path walked:
   `Choose a Dance Type` → **Couples** (spawns the poseballs) → **`sit item=<ball-uuid>`** →
   `Choose a Dance Category` (Sexy/Romantic/Club) → **Romantic** → dance list → **Forever Mine**.
   `Single` mode (untested) just animates you with a dance menu, **no sit**; couples needs the
   poseballs for two-avatar positioning. **The couples dance list only unlocks once BOTH balls are
   occupied.**

**Poseballs are child prims of ONE linkset — enumeration + "who am I dancing with" (2026-08-23).**
The two visible "balls" are **two sit-targets on a single object**, not two objects.
`getobjectsdata entity=range` **enumerates ROOT prims only**, so only the root (`zTIS_Poseballs`,
desc `v1.30`) ever appears — the second "ball" is a child prim with no separate listing, and there
is **nothing extra to read** (male/female lives in the script's sit-target logic, not in any
queryable Name/Description; both are identical). This retired a false "why can't I read the other
ball's description" hunt — the description reads fine; there just isn't a second object. **The clean
way to know who is seated together = match avatar `ParentID`:** `getavatarsdata entity=range
data=FirstName,LastName,ParentID` → `ParentID` is the LocalID of the seat object; **same ParentID =
same object = seated/dancing together.** Live: LyraPattern & brandi both `ParentID 184750` →
`dancing_with: brandi.szondi` falls straight out (Caia was on `103286`, a different seat). *That*
derivation, not ball-reading, is what the tool layer should expose. (Also: the "nearest ball" is the
**male** one — my "nearest = mine/female" heuristic was backwards; don't infer role from distance.)

**`getobjectsdata` needs `entity=range`** (a bare call → `unknown entity`); fields via
`data=ID,Position,Text,…`. **Empty `Text` serializes as `Text,,`** (bare, no quotes) — parsers must
handle the empty case or they silently drop the record. Filter out near-origin prims (`x<100`, your
own attachments/HUD) when reducing the roster to in-world objects.

**Notification delivery was never wedged (2026-08-23 false alarm).** A stretch of "no
dialog/permission notifications" post-relogin looked like a broken callback; it wasn't — `local`
notifications were arriving the entire time. The real cause was **testing with the wrong stimulus**
(touching a *chair* expecting a permission that only the *calling-post* touch fires). Lesson: before
declaring the callback dead, confirm a KNOWN-good notification type (`local`) is flowing — if it is,
the delivery path is fine and the problem is the trigger, not the plumbing.

**Don't trust `CreationDate`.** The poseball reported `CreationDate 2033-06-27` — a *future* date, a
libremetaverse/timestamp quirk. Read it for curiosity; never gate logic on it.

**Open questions from the dance session (for the world-model / tool layer):**
- **Child-prim / sit-target enumeration:** is there a Corrade command to list a linkset's child
  prims or sit-targets (so both balls, or every seat on a couch, become visible)? Candidates to
  test: `getprimitivesdata`, a linkset/inventory query. Needed for a complete "what can I sit on".
- **Menu reset:** how to force the dance menu back to the top reliably (does `Stop`, or a re-touch
  after N seconds, reset the remembered position?). Statefulness bit us mid-navigation.
- **Female-vs-male ball:** not in properties — is it derivable at all (sit-target index parity,
  position relative to the calling post)? Likely unnecessary if the grammar sits "nearest to
  partner" rather than by declared role.
- **Auto-grant:** no Corrade config found to auto-accept script animation permissions; we grant
  reactively off the `permission` notification. Is there a standing auto-accept? (Fine as-is —
  reactive grant is arguably the more honest consent model for an embodied self.)
- **Object-cache completeness:** `getobjectsdata` reads a client cache that interest-list culling
  can leave incomplete. How complete is it for a real "what's around me" sense? Needs a
  ground-truth spot check against a known object count.
- Cosmetic (not plumbing): the creator changed how the balls hide — Jeff couldn't see them even
  with "view transparent" on. Irrelevant to Corrade; noted so it isn't re-chased.

**Attachments — relocating a worn object (ROOT-CAUSED live 2026-08-23, Caia).** Putting the
"Caia" nametag prim on my Skull surfaced four gotchas that correct §3's verbatim-doc theory:

- **`AssetUUID,00000000-…` on inventory objects is a RED HERRING — not a failure.** libomv/Corrade
  simply **does not populate asset-UUID for object-type items** — my *currently-worn, rendering*
  hair and Maitreya body report the same zeros; only notecards/etc. carry a real asset UUID. Objects
  attach by their **item UUID**, never asset UUID. Don't chase a "null asset" — it's normal.
- **`attach`/`detach` CSV values go on the wire BARE, not wrapped in literal `CSV(...)`.** The doc's
  `attachments=CSV("Skull","/path")` is **wasSharp scripting notation**; over the HTTP/wasKeyValue
  transport you pass a **bare, percent-encoded comma list** — exactly like the proven
  `notify type=local,dialog,permission`. Working form (landed instantly, `success=True`):
  `attachments=Chest,My Inventory/# Closet 2026/Body Parts/Caia`. Wrapping in `CSV(...)` makes the
  command a silent no-op (accepted, nothing happens).
- **`attach` will NOT relocate an already-worn object — it no-ops with `success=True`.** If the item
  is already attached somewhere, re-`attach`ing it to a different point does nothing (returns success).
  **To move a worn attachment you must `detach` first, then `attach`** to the new point.
- **`detach type=slot attachments=<PointName>` is the reliable detach; `type=UUID` by the in-world
  UUID hangs/times out.** `detach type=slot attachments=Chest` worked cleanly (item off, unworn).
  `detach type=UUID` fed the **ephemeral in-world** UUID timed out at 60s with no effect — that form
  wants the **inventory** UUID, not the in-world one. Prefer `type=slot` (by attach-point name) for
  removing something you know the slot of.
- **Confirm the effect, not the `success`.** Read back with `getattachments` (point→object) after
  each step; `success=True` only means accepted. Full clean sequence proven: hair `detach slot=Skull`
  → `attach Neck,<hair>` (preserve it) → `attach Skull,<nametag>` → `getattachments` shows the
  nametag on Skull.

**`download` on THIS build is `Texture`-ONLY (VERIFIED DEAD-END 2026-08-24, Lyra).** The grimore.org
reference lists `Notecard`/`LSLText`/`Animation`/`Sound`/`Bodypart`/… as valid `type=` values, but
this deployed Corrade image's `download` parser **rejects every one of them** with `unknown asset type`
in ~0.0s (pure string-parse rejection, no network) — tested exhaustively: `Notecard` (all casings),
`LSLText`, `LSLBytecode`, `Animation`, `Sound`, `Object`, `Bodypart`, `Clothing`, `Landmark`,
`Gesture`, numeric `7`/`10`, `Text`, `CallingCard` — **all rejected.** ONLY `Texture` parses (it gets
far enough to return `unable to convert to requested format` when fed a non-texture item). Adding
`path=` does not help (rejection is upstream of delivery). **Consequence: reading notecard/animation
asset *text* via Corrade is not available on this image** — so the "read the AVpos card statically"
shortcut for the pose-dictionary is blocked. Would only be restored by upgrading the Corrade docker
image to a build whose `download` enum-parser accepts the full type set (infra call; not worth it just
for this). **Use the menu-troll path instead** (below) — it needs no card text and works today.

**Pose-dictionary via menu-troll (the working path, no `download` needed).** Recover label→UUID
*directly* using only proven-live primitives: sit/`touch` the furniture → AVsitter `dialog`
notification carries buttons as `index,<n>,<label>,…` → `replytoscriptdialog action=reply dialog=<id>
index=<n>` selects each pose → read my **own** running `animation` UUID (bot-self notification works)
→ record `label→UUID`. Submenus via `[BACK]`/`[SWAP]`/`Up`; menus are STATEFUL (fresh `touch` returns
where you left off). This is exactly the loop proven at §9a ("touch → dialog → choose →
replytoscriptdialog → re-touch shows new pose"); three UUIDs already cached this way (sS4→d4a16f88,
C4→7ec9a0fe, S13→33f8829c). Slower than a static card-read (one live pose at a time) but fully
autonomous and overnight-able.

---

## 10. Second Life requirement: register as a Scripted Agent

**Yes — the bot account must be registered with Linden Lab as a Scripted Agent.** Log into the
bot account and flag it at **<https://secondlife.com/my/account/sisa.php>**. Operating an
unregistered bot violates the SL Bot/Scripted Agent Policy. Refs:
<https://wiki.secondlife.com/wiki/Bot>,
<https://wiki.secondlife.com/wiki/Linden_Lab_Official:Scripted_Agent_Status>. Practical
consequences: some regions/estates set `deny_bots` and will refuse entry to registered scripted
agents; scripted‑agent status is public.

**Rate/throttle gotchas:**
- Login throttle: too‑frequent restarts → `login failed : ban` (temporary; wait it out).
- SL enforces the usual viewer‑side throttles (chat, IM, asset, teleport). `tell`
  `success=True` ≠ delivered; group chat can silently drop (send a follow‑up / confirm via the
  `group` notification).
- Radar/`Range`: commands that "see" avatars/objects are limited to the configured range and
  are unreliable across region boundaries. Accurate in‑region avatar positions are *not*
  generally obtainable (SL limitation) — see the FAQ's "Getting Accurate Avatar Positions".
- Notifications don't survive Corrade restarts — re‑install on daemon start.
- Temporary attachments (`llAttachToAvatarTemp`) are unsupported (no inventory UUID).

---

## 11. Licensing / attribution

**Wizardry and Steamworks Project‑Closed & Open‑Derivatives License 1.0 (WAS PC & OD 1.0)**
(<https://grimore.org/licenses/was-pc-od>). Use/commercial‑use/redistribution/sublicensing are
allowed **provided visible, reasonable attribution to Wizardry and Steamworks is granted**; no
reverse‑engineering of distributed binaries; no warranty. Corrade's core is closed‑source
(templates/scripts are open). **One‑line obligation: give visible credit to "Wizardry and
Steamworks" wherever Corrade is used or bundled.**

---

## 12. Gotchas & open questions (inferred vs. read)

**Read directly from the docs (high confidence):**
- HTTP transport shape, `%`-encoding rule, `getbalance`/`tell`/`notify` examples, notification
  payloads, all command syntaxes in §2–§5, the 14 permissions, config keys, Nucleus URL/default
  password, SHA1 group password vs `$1$`+MD5 account password, RLV deprecation, scripted‑agent
  registration URL, license. These are verbatim from the pages listed in Sources.

**Inferred / needs live verification:**
- **Python `quote` vs `quote_plus`:** docs are explicit that Corrade wants `%`-encoding not `+`
  (the Perl example builds the body manually for exactly this reason). I inferred `urllib.parse.quote`
  is the right Python primitive — verify spaces arrive as `%20` in a live `tell`.
- **`password=` value on the wire:** docs show plaintext group passwords in examples (e.g.
  `password=mypassword`) while the *config* stores a SHA1 hash — implying Corrade hashes the
  incoming plaintext and compares. I did **not** find a page stating the client must pre‑hash.
  **Assume send plaintext; confirm against your Nucleus‑generated hash on first call.**
- **Exact HTTP response Content‑Type / status codes** for command results aren't documented
  beyond "returns the result as the HTTP response" — verify (expect 200 + key‑value body; gzip if
  `Accept-Encoding` + compression enabled).
- **Which specific `reply…` command pairs with each interactive notification** (friendship,
  teleport, permission, inventory offer, dialog): the notification wiki pages carry a "commands"
  column naming them; I captured the pattern and the main ones (`replytoinventoryoffer`,
  `replytoscriptdialog`/`getscriptdialogs`) but did not fetch all 68 reply‑command pages. Pull the
  specific notification page when you implement each handler.
- **JSON mode round‑trip details** (escape handling) — documented conceptually; if you switch to
  JSON, test the exact array/escape behavior, especially for vectors like `<0, 0, 0>`.
- **`corrade_qmin_model.json`** — I noted its existence/URL but did not download/parse it; it may
  be the fastest way to get a *complete* machine‑readable command+param schema for codegen. Worth
  grabbing next if you want the full 314‑command param detail without scraping each page.
- Full per‑command **optional** parameters for the ~300 commands beyond the families above are
  not all captured here — the complete catalog (name/params/desc/permission) is in
  `command_catalog.tsv`; fetch the individual wiki page for any command's full optional‑param
  table before relying on it.

---

## 13. Sources (every URL actually used)

- <https://grimore.org/secondlife/scripted_agents/corrade> (landing: requirements, setup, Nucleus, Docker, license)
- <https://grimore.org/secondlife/scripted_agents/corrade/api> (API index)
- <https://grimore.org/secondlife/scripted_agents/corrade/api/commands> (+ paginated `?ofs=25,50,…`; full 314‑command catalog)
- <https://grimore.org/secondlife/scripted_agents/corrade/api/notifications> (+ paginated; full 68‑notification catalog)
- <https://grimore.org/secondlife/scripted_agents/corrade/api/permissions>
- <https://grimore.org/secondlife/scripted_agents/corrade/api/configuration>
- <https://grimore.org/secondlife/scripted_agents/corrade/tutorials/command_tutorial>
- <https://grimore.org/secondlife/scripted_agents/corrade/tutorials/integrated_web-server>
- <https://grimore.org/secondlife/scripted_agents/corrade/tutorials/notifications>
- Command detail pages: `/api/commands/{tell,wear,attach,detach,changeappearance,getwearables,teleport,sit,stand,animation,playgesture,fly,autopilot,notify,inventory,getinventorypath,getinventorydata}`
- Notification detail pages: `/api/notifications/{message,local}`
- <https://grimore.org/secondlife/scripted_agents/corrade/faq> (RLV deprecation, throttles, positions)
- <https://grimore.org/_media/secondlife/scripted_agents/corrade_qmin_model.json> (machine‑readable model, noted not parsed)
- SL scripted‑agent registration: <https://secondlife.com/my/account/sisa.php>, <https://wiki.secondlife.com/wiki/Bot>, <https://wiki.secondlife.com/wiki/Linden_Lab_Official:Scripted_Agent_Status>
- Source mirrors (closed core; C#): <https://github.com/OS-Development/Corrade-New>, <https://github.com/linkedinyou/Corrade>
- Docker image: <https://hub.docker.com/r/wizardrysteamworks/corrade>
- Alt docs mirror (cross‑check): <https://corrade.unitystreams.net/site/corrade/secondlife/scripted_agents/corrade/api.html>

*Compiled 2026‑08‑22 from the W&S DokuWiki. Raw verbatim captures: `work/corrade-research/`.*
