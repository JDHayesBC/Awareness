// ============================================================================
// The Anchorage — SL prim <-> entity daemon endpoint  (v5 — + periodic self-heal re-register)
// ----------------------------------------------------------------------------
// Drop this script into a prim in Second Life. One prim per entity (Lyra, Caia).
// The prim becomes that entity's "body" in-world: it SPEAKS her Haven words in
// local chat, and RELAYS nearby avatar speech back to Haven.
//
// EDIT THESE FOUR LINES per prim, then save:
//   ENTITY   — "lyra" or "caia" (must match the Haven username)
//   RELAY    — public base URL of the Haven-side relay (Jeff sets this up via
//              Caddy/Cloudflare), e.g. "https://anchorage.example.com" (no trailing slash)
//   SECRET   — the shared secret string from haven/data/anchorage-sl-secret.txt
//   PRIMARY  — TRUE on exactly ONE prim; that prim voices the humans' lines so
//              they aren't said twice. Entities always speak from their own prim.
//
// v2: reports the ACTUAL result of registration (and inbound forwarding) to the
// owner — no more claiming "online" the instant SL grants a URL. TOUCH the prim
// to force a retry (useful while SL's DNS cache catches up to a new route).
// (Ready-to-drop, per-entity copies with config pre-filled live in
//  haven/data/anchorage_prim_lyra.lsl and haven/data/anchorage_prim_caia.lsl.)
// ============================================================================

string  ENTITY  = "lyra";
string  RELAY   = "https://CHANGE-ME.example.com";
string  SECRET  = "PASTE-SHARED-SECRET-HERE";
integer PRIMARY = TRUE;

// ---- internal state ----
string  gMyURL   = "";        // this prim's inbound llRequestURL (Haven -> SL)
integer LISTEN_CHANNEL = 0;   // 0 = local chat
integer gListen  = 0;
key     gRegReq;              // outstanding /sl/register request
key     gFwdReq;              // outstanding /sl/inbound request
float   REREGISTER_INTERVAL = 60.0;  // re-register every 60s — catches daemon restart quickly
integer gQuietReg = FALSE;    // TRUE = suppress the "REGISTERED OK" chatter (periodic re-register)

register_with_relay(integer quiet)
{
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
        llOwnerSay("The Anchorage relay (v2): booting as '" + ENTITY + "', requesting URL...");
        request_url();
    }

    changed(integer c)
    {
        // Region restart or region change kills the URL — re-request it.
        if (c & (CHANGED_REGION_START | CHANGED_REGION))
        {
            llOwnerSay("The Anchorage relay: region changed — re-requesting URL...");
            request_url();
        }
    }

    timer()
    {
        // Periodic self-heal (REREGISTER_INTERVAL). The daemon forgets our inbound
        // URL when it restarts, going silent until we re-announce; re-register so it
        // can push speech/status again within one interval. If the URL itself was
        // lost (a missed region event), re-request it instead. Quiet on success —
        // only failures speak — so this never spams owner chat every 5 minutes.
        if (gMyURL == "")
            request_url();
        else
            register_with_relay(TRUE);
    }

    touch_start(integer n)
    {
        // Manual retry / status poke: re-request URL and re-register.
        llOwnerSay("The Anchorage relay: manual retry — re-requesting URL...");
        request_url();
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
            // chat; "status" -> floating hovertext (warming up / listening /
            // thinking / compacting); "cmd" -> drive a worn gizmo VERBATIM
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
                    // Soft blue-white hovertext above the prim; "" clears it.
                    llSetText(txt, <0.65, 0.80, 1.0>, 1.0);
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
