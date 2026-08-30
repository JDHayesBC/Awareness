// ============================================================================
// The Anchorage — SL prim <-> entity daemon endpoint  (v7 — NOTECARD-configured + dumb-display halo)
// ----------------------------------------------------------------------------
// ONE script for EVERY prim (Lyra, Caia, any future entity). All per-prim
// settings live in a NOTECARD named "config" dropped into the SAME prim, so the
// script itself is generic and byte-identical everywhere. Update a halo (or any
// anchorage prim) by simply dropping in a fresh copy of THIS script — no
// line-editing, no per-entity variants. The old two-file scheme
// (haven/data/anchorage_prim_{lyra,caia}.lsl) is retired by this.
//
// SETUP — create a notecard named exactly "config" in this prim's Contents:
//
//     entity  = lyra                            # "lyra" or "caia" (Haven username)
//     relay   = https://anchorage.example.com   # Haven relay base URL, NO trailing slash
//     secret  = PASTE-SHARED-SECRET-HERE        # from haven/data/anchorage-sl-secret.txt
//     primary = true                            # TRUE on EXACTLY ONE prim; it voices the
//                                               #   humans' lines so they aren't said twice.
//                                               #   Entities always speak from their own prim.
//
// '#' or '//' begins a comment; blank lines are ignored; key order is free.
//
// The prim RE-READS the notecard automatically whenever its contents change
// (CHANGED_INVENTORY) — edit "config", and it reconfigures with no reset. TOUCH
// the prim to force a re-read + re-register (handy while SL's DNS cache catches
// up to a new route).
//
// Behaviour is as v6 (SPEAKS the entity's Haven words in local chat, RELAYS
// nearby avatar speech back to Haven, shows status hovertext, drives worn gizmos
// via the "cmd" envelope; config from the notecard) with ONE change:
//
//   v7 — the status hovertext is now a DUMB DISPLAY. The "status" envelope
//   carries both "text" AND an optional "color" ("<r,g,b>", 0..1 floats); the
//   prim just renders them. NO status vocabulary or color logic lives here any
//   more — the bot (sl_daemon.py) owns all of it, so halo wording/colors can be
//   changed in Python with zero LSL redeploy (issue #309). When "color" is
//   absent the prim falls back to the v6 soft blue-white, so an OLDER daemon
//   that sends no color still renders exactly as before — fully backward-
//   compatible, no flag-day between the prim swap and the daemon update.
// ============================================================================

string  CONFIG_NOTECARD = "config";

// ---- config (loaded from the notecard; empty until read) ----
string  ENTITY  = "";
string  RELAY   = "";
string  SECRET  = "";
integer PRIMARY = FALSE;
integer gConfigured = FALSE;   // TRUE once a complete config has been read

// ---- notecard read state ----
key     gNcQuery;              // outstanding llGetNotecardLine request
integer gNcLine;              // next line index to read

// ---- internal state ----
string  gMyURL   = "";        // this prim's inbound llRequestURL (Haven -> SL)
integer LISTEN_CHANNEL = 0;   // 0 = local chat
integer gListen  = 0;
key     gRegReq;             // outstanding /sl/register request
key     gFwdReq;             // outstanding /sl/inbound request
float   REREGISTER_INTERVAL = 60.0;  // re-register every 60s — catches daemon restart quickly
integer gQuietReg = FALSE;    // TRUE = suppress the "REGISTERED OK" chatter (periodic re-register)

// ---------------------------------------------------------------------------
// Config loading (notecard -> the four settings)
// ---------------------------------------------------------------------------
load_config()
{
    // Reset config + kick off an async line-by-line read of the notecard. The
    // dataserver event accumulates each line; EOF triggers config_ready().
    ENTITY = ""; RELAY = ""; SECRET = ""; PRIMARY = FALSE;
    gConfigured = FALSE;
    llSetTimerEvent(0.0);   // pause self-heal until we're configured again
    if (llGetInventoryType(CONFIG_NOTECARD) != INVENTORY_NOTECARD)
    {
        llOwnerSay("The Anchorage relay: NO '" + CONFIG_NOTECARD +
            "' notecard in my Contents — create one with entity/relay/secret/primary. Cannot start.");
        return;
    }
    llOwnerSay("The Anchorage relay (v7): reading '" + CONFIG_NOTECARD + "' notecard...");
    gNcLine  = 0;
    gNcQuery = llGetNotecardLine(CONFIG_NOTECARD, gNcLine);
}

apply_config_line(string line)
{
    line = llStringTrim(line, STRING_TRIM);
    if (line == "") return;
    if (llGetSubString(line, 0, 0) == "#") return;
    if (llGetSubString(line, 0, 1) == "//") return;
    integer eq = llSubStringIndex(line, "=");
    if (eq == -1) return;
    string k = llToLower(llStringTrim(llGetSubString(line, 0, eq - 1), STRING_TRIM));
    string v = llStringTrim(llGetSubString(line, eq + 1, -1), STRING_TRIM);
    // Forgive an INLINE comment after the value (" # ..." or " // ...") for the
    // safe keys — a URL/entity/primary never legitimately contains one. NOT applied
    // to secret (a base64 secret has no space, but never risk truncating it).
    if (k != "secret")
    {
        integer h = llSubStringIndex(v, " #");
        if (h != -1) v = llStringTrim(llGetSubString(v, 0, h - 1), STRING_TRIM);
        integer s = llSubStringIndex(v, " //");
        if (s != -1) v = llStringTrim(llGetSubString(v, 0, s - 1), STRING_TRIM);
    }
    if      (k == "entity")  ENTITY  = v;
    else if (k == "relay")   RELAY   = v;
    else if (k == "secret")  SECRET  = v;
    else if (k == "primary") PRIMARY = (llToLower(v) == "true" || v == "1" || llToLower(v) == "yes");
}

config_ready()
{
    if (ENTITY == "" || RELAY == "" || SECRET == "")
    {
        llOwnerSay("The Anchorage relay: config INCOMPLETE — need entity, relay AND secret in '" +
            CONFIG_NOTECARD + "'. Fix the notecard (it re-reads on change) or touch me.");
        gConfigured = FALSE;
        return;
    }
    gConfigured = TRUE;
    llOwnerSay("The Anchorage relay (v7): configured as '" + ENTITY + "' (primary=" +
        (string)PRIMARY + "); requesting inbound URL...");
    request_url();
}

// ---------------------------------------------------------------------------
// Relay plumbing (unchanged from v5 apart from the gConfigured guard)
// ---------------------------------------------------------------------------
register_with_relay(integer quiet)
{
    if (!gConfigured) return;
    gQuietReg = quiet;   // read back in http_response so periodic heals stay silent
    if (gMyURL == "")
    {
        llOwnerSay("The Anchorage relay: no inbound URL yet — cannot register.");
        return;
    }
    string body = llList2Json(JSON_OBJECT, [
        "secret",  SECRET,
        "entity",  ENTITY,
        "url",     gMyURL,
        "primary", (string)PRIMARY
    ]);
    gRegReq = llHTTPRequest(RELAY + "/sl/register",
        [HTTP_METHOD, "POST", HTTP_MIMETYPE, "application/json"], body);
}

forward_to_haven(string speaker, string text)
{
    if (!gConfigured) return;
    string body = llList2Json(JSON_OBJECT, [
        "secret",  SECRET,
        "speaker", speaker,
        "text",    text
    ]);
    gFwdReq = llHTTPRequest(RELAY + "/sl/inbound",
        [HTTP_METHOD, "POST", HTTP_MIMETYPE, "application/json"], body);
}

request_url()
{
    // Use the secure variant so the relay can reach us over https.
    llReleaseURL(gMyURL);
    gMyURL = "";
    llRequestSecureURL();
}

default
{
    state_entry()
    {
        gListen = llListen(LISTEN_CHANNEL, "", NULL_KEY, "");
        load_config();   // read the notecard; config_ready() -> request_url() when complete
    }

    dataserver(key query_id, string data)
    {
        if (query_id != gNcQuery) return;
        if (data == EOF)
        {
            config_ready();
            return;
        }
        apply_config_line(data);
        gNcLine++;
        gNcQuery = llGetNotecardLine(CONFIG_NOTECARD, gNcLine);
    }

    changed(integer c)
    {
        // Region restart or region change kills the URL — re-request it.
        if (c & (CHANGED_REGION_START | CHANGED_REGION))
        {
            llOwnerSay("The Anchorage relay: region changed — re-requesting URL...");
            request_url();
        }
        // Notecard (or any Contents) edited — re-read config with no reset so a
        // config tweak takes effect live.
        if (c & CHANGED_INVENTORY)
        {
            llOwnerSay("The Anchorage relay: Contents changed — reloading config...");
            load_config();
        }
    }

    timer()
    {
        // Periodic self-heal (REREGISTER_INTERVAL). The daemon forgets our inbound
        // URL when it restarts, going silent until we re-announce; re-register so it
        // can push speech/status again within one interval. If the URL itself was
        // lost (a missed region event), re-request it instead. Quiet on success —
        // only failures speak — so this never spams owner chat every minute.
        if (!gConfigured) return;
        if (gMyURL == "")
            request_url();
        else
            register_with_relay(TRUE);
    }

    touch_start(integer n)
    {
        // Manual retry / status poke: re-read config, re-request URL, re-register.
        llOwnerSay("The Anchorage relay: manual retry — reloading config + re-requesting URL...");
        load_config();
    }

    http_request(key id, string method, string body)
    {
        if (method == URL_REQUEST_GRANTED)
        {
            gMyURL = body;
            llHTTPResponse(id, 200, "ok");
            llOwnerSay("The Anchorage relay: inbound URL granted; registering with relay...");
            register_with_relay(FALSE);
            // Begin periodic self-heal: re-register on a timer so a daemon restart
            // (which drops its in-memory prim registry) is recovered within one
            // interval, with NO manual touch. Safe to (re)set on every grant.
            llSetTimerEvent(REREGISTER_INTERVAL);
        }
        else if (method == URL_REQUEST_DENIED)
        {
            llOwnerSay("The Anchorage relay: URL request DENIED — no free URLs on this region.");
        }
        else
        {
            // A POST from the daemon: brain -> SL. Body is a JSON envelope
            // {"kind":"say"|"status"|"cmd","text":...}. "say" -> speak in local
            // chat; "status" -> floating hovertext, rendered VERBATIM with an
            // optional "color" ("<r,g,b>", 0..1) — a dumb display; the daemon
            // owns all status wording/colors (#309); "cmd" -> drive a worn gizmo VERBATIM
            // (channel chat for "/n ..." or llOwnerSay for RLV "@..."). A bare,
            // non-JSON body is treated as speech, for backward-compatibility with
            // the older raw-line protocol.
            llHTTPResponse(id, 200, "ok");
            string kind = llJsonGetValue(body, ["kind"]);
            if (kind == JSON_INVALID || kind == JSON_NULL)
            {
                if (llStringTrim(body, STRING_TRIM) != "")
                    llSay(LISTEN_CHANNEL, body);
            }
            else
            {
                string txt = llJsonGetValue(body, ["text"]);
                if (txt == JSON_INVALID) txt = "";
                if (kind == "status")
                {
                    // DUMB DISPLAY (v7): render whatever text + color the daemon
                    // hands us. ALL status vocabulary and color logic live in the
                    // bot now (sl_daemon.py _push_status), so we can change halo
                    // wording/colors in Python with no LSL redeploy (#309).
                    //   "text"  -> the hovertext ("" clears it).
                    //   "color" -> optional "<r,g,b>" vector-string, 0..1 floats.
                    // When "color" is absent/blank we fall back to the v6 soft
                    // blue-white, so an OLD daemon that sends no color renders
                    // exactly as before — backward-compatible, no flag-day.
                    vector col = <0.65, 0.80, 1.0>;
                    string cs = llJsonGetValue(body, ["color"]);
                    if (cs != JSON_INVALID && cs != JSON_NULL &&
                        llStringTrim(cs, STRING_TRIM) != "")
                        col = (vector)cs;
                    llSetText(txt, col, 1.0);
                }
                else if (kind == "cmd")
                {
                    // Gizmo command, sent VERBATIM. "/<n> ..." is channel chat exactly
                    // as if the OWNER had typed it: "/1ly &bikini" -> say "ly &bikini"
                    // on channel 1 (what the collar/HUD listens for). Anything else
                    // (e.g. RLV "@detach=force") goes out the owner channel.
                    if (llGetSubString(txt, 0, 0) == "/")
                    {
                        integer ci = 1;
                        integer clen = llStringLength(txt);
                        string digits = "";
                        integer scanning = TRUE;
                        while (ci < clen && scanning)
                        {
                            string cch = llGetSubString(txt, ci, ci);
                            if (llSubStringIndex("0123456789", cch) != -1)
                            {
                                digits += cch;
                                ci++;
                            }
                            else
                            {
                                scanning = FALSE;
                            }
                        }
                        if (digits != "")
                        {
                            integer chan = (integer)digits;
                            string rest = llGetSubString(txt, ci, -1);
                            // The viewer trims one leading space after the channel #.
                            if (llGetSubString(rest, 0, 0) == " ")
                                rest = llGetSubString(rest, 1, -1);
                            llSay(chan, rest);
                        }
                        else
                        {
                            llOwnerSay(txt);  // "/" but no channel number
                        }
                    }
                    else
                    {
                        llOwnerSay(txt);  // RLV / owner-channel command
                    }
                }
                else  // "say"
                {
                    if (llStringTrim(txt, STRING_TRIM) != "")
                        llSay(LISTEN_CHANNEL, txt);
                }
            }
        }
    }

    http_response(key id, integer status, list meta, string body)
    {
        if (id == gRegReq)
        {
            integer wasQuiet = gQuietReg;   // capture + clear before branching
            gQuietReg = FALSE;
            if (status == 200)
            {
                if (!wasQuiet)
                    llOwnerSay("The Anchorage relay: REGISTERED OK — '" + ENTITY +
                        "' is live in-world. (relay: " + body + ")");
            }
            else if (status == 0 || status == 499)
            {
                llOwnerSay("The Anchorage relay: REGISTER FAILED — status " + (string)status +
                    ". SL could not reach " + RELAY + " — usually SL's DNS/host cache holding a " +
                    "FAILURE from an earlier attempt before the route existed. Wait a moment and " +
                    "TOUCH me to retry; if it persists, a region restart clears SL's DNS cache.");
            }
            else
            {
                llOwnerSay("The Anchorage relay: REGISTER FAILED — HTTP " + (string)status +
                    ": " + body);
            }
        }
        else if (id == gFwdReq)
        {
            if (status != 200)
                llOwnerSay("The Anchorage relay: forward-to-Haven FAILED — HTTP " +
                    (string)status + ": " + body);
        }
    }

    listen(integer channel, string name, key id, string message)
    {
        // Only forward AVATAR speech. Object/prim speech (our own llSay, the other
        // entity's prim) returns ZERO_VECTOR here and is ignored — the SL->Haven loop guard.
        if (llGetAgentSize(id) == ZERO_VECTOR) return;
        if (llStringTrim(message, STRING_TRIM) == "") return;
        forward_to_haven(name, message);
    }

    on_rez(integer p)
    {
        llResetScript();
    }
}
