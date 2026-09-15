/**
 * Haven — WebSocket chat client
 */
const haven = (() => {
    let ws = null;
    let currentUser = null;
    let currentRoomId = null;
    let rooms = [];
    let users = [];  // global roster (#319: "Global Users")
    let roomMembers = [];  // members of currentRoomId only (#319: "Current Room")
    let reconnectTimer = null;
    let reconnectAttempt = 0;
    let reconnectingBannerTimer = null;
    let typingTimer = null;
    let typingUsers = {};  // room_id -> {username -> timeout}
    let oldestMessageId = {};  // room_id -> oldest message id loaded
    let hasMore = {};  // room_id -> bool
    let unread = {};  // room_id -> count
    let nicknames = {};  // target_id -> nickname string (#289)
    let pendingRoomId = null;  // deep-link target from a notification, applied once connected
    let lastActivity = Date.now();  // last real user interaction with this tab
    const IDLE_MS = 60000;  // visible-but-untouched this long => not actively "viewing"
    let userAtBottom = true;  // tracks whether scroll is anchored at bottom
    const SCROLL_BOTTOM_THRESHOLD = 120;  // px from bottom to count as "at bottom"
    const originalTitle = document.title;

    const $ = (id) => document.getElementById(id);

    // --- Nickname helpers (#289) ---

    // Return the viewer's nickname for a user, falling back to display_name.
    function resolveDisplayName(user) {
        return (user && nicknames[user.id]) ? nicknames[user.id] : (user ? user.display_name : '');
    }

    async function fetchNicknames() {
        const token = getToken();
        if (!token) return;
        try {
            const res = await fetch('/api/nicknames', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                nicknames = data.nicknames || {};
            }
        } catch (e) {
            console.warn('[Haven] Could not fetch nicknames:', e);
        }
    }

    // --- Auth ---

    function getToken() {
        return localStorage.getItem('haven_token');
    }

    function setToken(token) {
        localStorage.setItem('haven_token', token);
    }

    function clearToken() {
        localStorage.removeItem('haven_token');
    }

    // --- Room-selection persistence (#318) ---
    // `currentRoomId` (in-memory) only survives WS reconnects within the SAME
    // page load. A genuine page reload — browser refresh, PWA relaunch, a
    // mobile tab that got discarded and reopened, or a service-worker update
    // that forces a hard navigation — starts a fresh JS context where
    // currentRoomId is null, so without a durable fallback it always fell
    // through to rooms[0]. That was the second, rarer culprit behind #318:
    // the first fix only covered same-session WS reconnects. localStorage
    // closes the remaining gap.
    const ROOM_STORAGE_KEY = 'haven_current_room';

    function getSavedRoomId() {
        return localStorage.getItem(ROOM_STORAGE_KEY);
    }

    function saveCurrentRoomId(roomId) {
        if (roomId) {
            localStorage.setItem(ROOM_STORAGE_KEY, roomId);
        } else {
            localStorage.removeItem(ROOM_STORAGE_KEY);
        }
    }

    // --- Login ---

    function initLogin() {
        // Handle Google OAuth callback: token arrives in URL fragment
        const hash = location.hash;
        if (hash.startsWith('#token=')) {
            const token = decodeURIComponent(hash.slice(7));
            history.replaceState(null, '', '/');
            setToken(token);
            connect();
            return;
        }

        // Handle OAuth errors passed as query params
        const params = new URLSearchParams(location.search);
        if (params.has('auth_error')) {
            showLogin(decodeURIComponent(params.get('auth_error')));
            history.replaceState(null, '', '/');
        }

        const usernameInput = $('username-input');
        const passwordInput = $('password-input');
        const loginBtn = $('login-btn');
        const googleBtn = $('google-btn');  // null if Google not configured

        const doLogin = async () => {
            const username = usernameInput.value.trim();
            const password = passwordInput.value;
            if (!username || !password) return;

            loginBtn.disabled = true;
            loginBtn.textContent = 'Signing in...';

            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    showLogin(err.detail || 'Invalid credentials');
                    return;
                }
                const { token } = await res.json();
                setToken(token);
                $('login-error').classList.add('hidden');
                connect();
            } catch (e) {
                showLogin('Connection error — try again');
            } finally {
                loginBtn.disabled = false;
                loginBtn.textContent = 'Sign in';
            }
        };

        loginBtn.addEventListener('click', doLogin);
        passwordInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') doLogin();
        });
        usernameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') passwordInput.focus();
        });

        if (googleBtn) {
            googleBtn.addEventListener('click', () => { location.href = '/auth/google'; });
        }

        // Auto-connect if token already saved
        if (getToken()) {
            connect();
        }
    }

    // --- WebSocket ---

    function connect() {
        const token = getToken();
        if (!token) return;

        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${proto}//${location.host}/ws?token=${encodeURIComponent(token)}`;

        try {
            ws = new WebSocket(url);
        } catch (_) {
            scheduleReconnect();
            return;
        }

        ws.onopen = () => {
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            reconnectAttempt = 0;
            hideReconnectingBanner();
            // Tell the server whether this tab is actively being viewed, so it
            // knows whether we still need a push for new messages.
            sendActive();
        };

        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            handleEvent(data);
        };

        ws.onclose = (e) => {
            if (e.code === 4001) {
                // Auth failed
                clearToken();
                showLogin('Invalid token');
                return;
            }
            scheduleReconnect();
        };

        ws.onerror = () => {};
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;  // already scheduled
        // We keep the socket even while hidden/idle (real-time stays ready); the
        // server relies on our active/idle report, not on us disconnecting, to
        // decide push eligibility. So it's safe to reconnect regardless of tab
        // visibility. On a truly frozen mobile tab this loop simply won't run.
        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, capped at 30s
        const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttempt));
        reconnectAttempt++;
        // Show banner after 1s — avoids flicker on quick reconnects
        if (!reconnectingBannerTimer) {
            reconnectingBannerTimer = setTimeout(() => {
                showReconnectingBanner();
                reconnectingBannerTimer = null;
            }, 1000);
        }
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connect();
        }, delay);
    }

    function reconnectNow() {
        // Cancel any pending backoff timer and try immediately. Used by
        // visibilitychange and online events — when context changes, don't
        // make the user wait 16s for the next backoff slot.
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        reconnectAttempt = 0;
        if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
            connect();
        }
    }

    function showReconnectingBanner() {
        let banner = $('reconnecting-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'reconnecting-banner';
            banner.className = 'reconnecting-banner';
            banner.textContent = 'Reconnecting…';
            document.body.appendChild(banner);
        }
        banner.classList.remove('hidden');
    }

    function hideReconnectingBanner() {
        if (reconnectingBannerTimer) {
            clearTimeout(reconnectingBannerTimer);
            reconnectingBannerTimer = null;
        }
        const banner = $('reconnecting-banner');
        if (banner) banner.classList.add('hidden');
    }

    function send(msg) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(msg));
        }
    }

    // --- Active/idle reporting ---
    // A device only suppresses push on the user's OTHER devices while it's
    // genuinely being looked at: tab visible AND interacted-with recently. An
    // open-but-idle tab (e.g. Haven sitting behind the terminal) reports
    // inactive, so the phone still rings.

    function isActive() {
        return document.visibilityState === 'visible' && (Date.now() - lastActivity) < IDLE_MS;
    }

    function sendActive() {
        send({ type: 'active', active: isActive() });
    }

    function markActivity() {
        const wasInactive = !isActive();
        lastActivity = Date.now();
        // Only ping the server on an idle/hidden -> active transition. Steady
        // state rides the 30s pong; active -> idle is purely time-based.
        if (wasInactive && isActive()) sendActive();
    }

    // --- Event handlers ---

    function handleEvent(data) {
        switch (data.type) {
            case 'ping':
                // Server liveness probe. Answering proves this tab is really
                // running (not frozen/suspended by the OS), and piggybacks our
                // current active/idle state so the server knows whether we're
                // actually being looked at. A backgrounded/locked device stops
                // answering (liveness) and reports inactive when it can.
                send({ type: 'pong', active: isActive() });
                break;
            case 'connected':
                onConnected(data);
                break;
            case 'message':
                onMessage(data);
                break;
            case 'history':
                onHistory(data);
                break;
            case 'presence':
                onPresence(data);
                break;
            case 'typing':
                onTyping(data);
                break;
            case 'member_joined':
                onMemberJoined(data);
                break;
            case 'member_left':
                onMemberLeft(data);
                break;
            case 'room_updated':
                onRoomUpdated(data);
                break;
        }
    }

    function onConnected(data) {
        currentUser = data.user;
        rooms = data.rooms;
        users = data.users;
        // Seed per-room unread badges from the server (durable across reconnects).
        unread = data.unread || {};

        // Load nicknames so resolveDisplayName works before first render.
        fetchNicknames();

        $('login-screen').classList.add('hidden');
        $('chat-app').classList.remove('hidden');
        $('current-user').textContent = currentUser.display_name;

        // Show admin link if user is admin
        if (currentUser.is_admin) {
            const adminLink = $('admin-link');
            if (adminLink) adminLink.style.display = '';
        }

        renderRooms();
        renderUsers();

        // Enable input
        $('message-input').disabled = false;
        $('send-btn').disabled = false;
        $('attach-btn').disabled = false;

        // Choose which room to land in. Priority: a deep-link target (from a
        // tapped notification — via ?room= on a cold open, or a stashed
        // postMessage), then the in-memory current room (same-session WS
        // reconnect), then the last room saved to localStorage (survives a
        // genuine page reload — see #318 comment on ROOM_STORAGE_KEY above),
        // and only then the first room as a last resort.
        const urlRoom = new URLSearchParams(location.search).get('room');
        const wanted = pendingRoomId || urlRoom;
        pendingRoomId = null;
        const savedRoomId = getSavedRoomId();
        let target = null;
        if (wanted && rooms.some(r => r.id === wanted)) {
            target = wanted;
        } else if (currentRoomId && rooms.some(r => r.id === currentRoomId)) {
            // Preserve the room across reconnects. onConnected fires on EVERY
            // (re)connect, not just cold open — so without this, an idle-triggered
            // reconnect (missed pong / throttled timers on an idle tab) bounces the
            // user back to rooms[0]. That was the "flash + reset to first room" bug
            // (first fix, #318).
            target = currentRoomId;
        } else if (savedRoomId && rooms.some(r => r.id === savedRoomId)) {
            // No in-memory room (fresh page load) but we have a durable record
            // of the last room the user was in — restore it instead of
            // defaulting to rooms[0]. This is the SECOND #318 culprit: a real
            // reload (refresh / PWA relaunch / discarded-tab reopen / SW-forced
            // hard nav) always starts with currentRoomId === null.
            target = savedRoomId;
        } else if (rooms.length > 0) {
            // Genuinely no current room to restore (first-ever login, or the
            // saved/current room no longer exists e.g. we were removed from it).
            target = rooms[0].id;
        }
        if (target) selectRoom(target);
        // Strip the ?room= param so a manual refresh doesn't re-force it.
        if (urlRoom && location.search) {
            history.replaceState(null, '', location.pathname);
        }
    }

    function onMessage(data) {
        // Clear typing indicator for the sender (they finished typing)
        if (typingUsers[data.room_id] && typingUsers[data.room_id][data.username]) {
            clearTimeout(typingUsers[data.room_id][data.username]);
            delete typingUsers[data.room_id][data.username];
            updateTypingIndicator();
        }

        if (data.room_id === currentRoomId) {
            const isMine = currentUser && data.username === currentUser.username;
            const wasAtBottom = userAtBottom;
            appendMessage(data);
            // Only auto-scroll if user is at bottom or sent the message themselves.
            // Avoids yanking the view when reading older history.
            if (isMine || wasAtBottom) {
                scrollToBottom();
            }
            // We're viewing this room — keep the server read marker current so a
            // reconnect doesn't resurrect an already-seen message as unread.
            send({ type: 'read', room_id: data.room_id });
        } else {
            // Track unread for non-active rooms
            if (!unread[data.room_id]) unread[data.room_id] = 0;
            unread[data.room_id]++;
            renderRooms();
            updateTitle();
        }
    }

    function onHistory(data) {
        if (data.room_id !== currentRoomId) return;

        const list = $('message-list');
        const prevHeight = list.scrollHeight;

        // Prepend messages (they come oldest-first)
        const frag = document.createDocumentFragment();
        data.messages.forEach(m => {
            frag.appendChild(createMessageEl(m));
            trackOldest(m.room_id, m.id);
        });
        list.insertBefore(frag, list.firstChild);

        const isInitialLoad = prevHeight === 0;
        hasMore[data.room_id] = data.has_more;
        $('load-more').classList.toggle('hidden', !data.has_more);

        const messages = $('messages');
        if (isInitialLoad) {
            // First batch of history for this room — scroll to bottom.
            // Wait a frame so layout settles (esp. for image messages whose
            // height depends on async image decode).
            requestAnimationFrame(() => scrollToBottom());
        } else {
            // Pagination: maintain scroll position so user stays anchored to
            // the message they were reading.
            messages.scrollTop += list.scrollHeight - prevHeight;
        }
    }

    function onPresence(data) {
        const user = users.find(u => u.id === data.user_id);
        if (user) {
            user.online = data.status === 'online';
            renderUsers();
        }
    }

    function onTyping(data) {
        if (data.room_id !== currentRoomId) return;
        if (data.username === currentUser.username) return;

        // Bots take longer to respond (5-30s) — use longer typing timeout
        const isBot = users.some(u => u.username === data.username && u.is_bot);
        const timeout = isBot ? 45000 : 3000;

        if (!typingUsers[data.room_id]) typingUsers[data.room_id] = {};
        clearTimeout(typingUsers[data.room_id][data.username]);
        typingUsers[data.room_id][data.username] = setTimeout(() => {
            delete typingUsers[data.room_id][data.username];
            updateTypingIndicator();
        }, timeout);
        updateTypingIndicator();
    }

    function onMemberJoined(data) {
        if (data.room_id === currentRoomId) {
            appendSystemMessage(`${escapeHtml(data.display_name)} joined`);
            loadRoomMembers(currentRoomId);  // #319: refresh "Current Room" panel
        }
    }

    function onMemberLeft(data) {
        if (data.room_id === currentRoomId) {
            appendSystemMessage(`${escapeHtml(data.username)} left`);
            loadRoomMembers(currentRoomId);  // #319: refresh "Current Room" panel
        }
        if (currentUser && data.user_id === currentUser.id) {
            // We left — remove room from sidebar and switch
            rooms = rooms.filter(r => r.id !== data.room_id);
            renderRooms();
            if (currentRoomId === data.room_id) {
                currentRoomId = null;
                $('room-name').textContent = '';
                $('message-list').innerHTML = '';
                // Trigger: we were removed from (or left) the room we were
                // currently viewing. rooms[0] is a legitimate fallback HERE —
                // the room we had selected genuinely no longer exists for us,
                // so there is nothing to "preserve". selectRoom() below will
                // overwrite the stale localStorage entry with this new pick.
                if (rooms.length > 0) selectRoom(rooms[0].id);
                else { saveCurrentRoomId(null); roomMembers = []; renderRoomUsers(); }
            }
        }
    }

    function onRoomUpdated(data) {
        // Update rooms array and re-render header + sidebar
        const room = rooms.find(r => r.id === data.room_id);
        if (room) {
            room.display_name = data.display_name;
            renderRooms();
        }
        if (data.room_id === currentRoomId && room) {
            $('room-name').textContent = room.is_dm ? room.display_name : `# ${room.display_name}`;
        }
    }

    // --- Rendering ---

    // For a DM room, return the OTHER participant's user object (or null).
    function dmOtherUser(room) {
        if (!room.is_dm || !currentUser) return null;
        // DM room name is dm-{user1}-{user2}; strip the "dm-" prefix and split by "-"
        // But usernames can contain hyphens, so match by trying both orderings.
        for (const u of users) {
            if (u.id !== currentUser.id) {
                const n1 = `dm-${currentUser.username}-${u.username}`;
                const n2 = `dm-${u.username}-${currentUser.username}`;
                if (room.name === n1 || room.name === n2) return u;
            }
        }
        return null;
    }

    // Return display label for a room, applying nickname for DMs.
    function roomDisplayLabel(room) {
        if (room.is_dm) {
            const other = dmOtherUser(room);
            return other ? resolveDisplayName(other) : room.display_name;
        }
        return `# ${room.display_name}`;
    }

    function renderRooms() {
        const roomList = $('room-list');
        const dmList = $('dm-list');
        roomList.innerHTML = '';
        dmList.innerHTML = '';

        let hasDMs = false;
        rooms.forEach(r => {
            const el = document.createElement('div');
            el.className = 'room-item' + (r.id === currentRoomId ? ' active' : '');

            const label = roomDisplayLabel(r);
            const count = unread[r.id] || 0;

            if (count > 0 && r.id !== currentRoomId) {
                el.innerHTML = `
                    <span class="flex-1 truncate">${escapeHtml(label)}</span>
                    <span class="unread-badge">${count > 99 ? '99+' : count}</span>
                `;
                el.classList.add('has-unread');
            } else {
                el.textContent = label;
            }

            el.addEventListener('click', () => selectRoom(r.id));

            if (r.is_dm) {
                dmList.appendChild(el);
                hasDMs = true;
            } else {
                roomList.appendChild(el);
            }
        });

        $('dm-section').classList.toggle('hidden', !hasDMs);
    }

    function sortUsersOnlineFirst(list) {
        // Online first, then alphabetical
        return [...list].sort((a, b) => {
            if (a.online !== b.online) return a.online ? -1 : 1;
            return a.username.localeCompare(b.username);
        });
    }

    function buildUserItemEl(u) {
        const el = document.createElement('div');
        el.className = 'user-item';
        el.title = `Click to DM @${u.username}`;
        const displayName = resolveDisplayName(u);
        const renameBtn = (currentUser && u.id !== currentUser.id)
            ? `<button class="rename-user-btn" title="Rename ${escapeHtml(u.username)}">✏️</button>`
            : '';
        el.innerHTML = `
            <span class="status-dot ${u.online ? 'online' : 'offline'}"></span>
            <span class="user-display-name">${escapeHtml(displayName)}</span>
            ${u.is_bot ? '<span class="bot-tag">entity</span>' : ''}
            ${renameBtn}
        `;
        // Click to start DM (on the name area, not the rename button)
        if (currentUser && u.id !== currentUser.id) {
            el.querySelector('.user-display-name').addEventListener('click', () => startDM(u.username));
            el.querySelector('.status-dot').addEventListener('click', () => startDM(u.username));
            const btn = el.querySelector('.rename-user-btn');
            if (btn) {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    promptRenameUser(u);
                });
            }
        }
        return el;
    }

    async function promptRenameUser(u) {
        const current = nicknames[u.id] || '';
        const input = prompt(`Nickname for ${u.display_name} (@${u.username}):\n(leave blank to clear)`, current);
        if (input === null) return;  // cancelled

        const token = getToken();
        try {
            if (input.trim() === '') {
                // Clear nickname
                const res = await fetch(`/api/nicknames/${u.id}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` },
                });
                if (res.ok) {
                    delete nicknames[u.id];
                }
            } else {
                const res = await fetch(`/api/nicknames/${u.id}`, {
                    method: 'PUT',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ nickname: input.trim() }),
                });
                if (res.ok) {
                    nicknames[u.id] = input.trim();
                }
            }
            // Re-render user lists and sidebar (DM labels may have changed)
            renderUsers();
            renderRooms();
            // Update header if current room is a DM with this user
            if (currentRoomId) {
                const room = rooms.find(r => r.id === currentRoomId);
                if (room) $('room-name').textContent = roomDisplayLabel(room);
            }
        } catch (e) {
            console.error('[Haven] rename user failed:', e);
        }
    }

    function renderUsers() {
        const list = $('user-list');
        list.innerHTML = '';
        sortUsersOnlineFirst(users).forEach(u => list.appendChild(buildUserItemEl(u)));
        // Room membership doesn't change when someone's online status flips,
        // but the room panel's status DOTS need the same refresh (#319).
        renderRoomUsers();
    }

    // --- Current-room members (#319) ---
    // `roomMembers` holds member id/username/display_name/is_bot for
    // currentRoomId (fetched via the existing /members endpoint — the server
    // already knows membership, so no derivation from presence is needed).
    // Online status is cross-referenced from the global `users` roster,
    // which is kept live by the `presence` WS event.
    async function loadRoomMembers(roomId) {
        if (!roomId) { roomMembers = []; renderRoomUsers(); return; }
        const token = getToken();
        try {
            const res = await fetch(`/api/rooms/${roomId}/members`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!res.ok) { roomMembers = []; renderRoomUsers(); return; }
            const { members } = await res.json();
            // Guard against a stale response landing after the user has
            // already switched rooms again.
            if (roomId !== currentRoomId) return;
            roomMembers = members;
        } catch (e) {
            roomMembers = [];
        }
        renderRoomUsers();
    }

    function renderRoomUsers() {
        const list = $('room-user-list');
        if (!list) return;
        list.innerHTML = '';
        const withPresence = roomMembers.map(m => {
            const live = users.find(u => u.id === m.id);
            return { ...m, online: live ? live.online : false };
        });
        sortUsersOnlineFirst(withPresence).forEach(u => list.appendChild(buildUserItemEl(u)));
    }

    async function startDM(username) {
        const token = getToken();
        try {
            const res = await fetch(`/api/dm/${username}`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!res.ok) return;
            const room = await res.json();
            // Add to rooms if not already there
            if (!rooms.find(r => r.id === room.id)) {
                rooms.push(room);
                renderRooms();
            }
            selectRoom(room.id);
        } catch (e) {
            console.error('DM creation failed:', e);
        }
    }

    // --- Create Room (#320) ---
    // Minimal by design (Crusher marked this low priority): a single prompt
    // for the display name, auto-derived slug, reuses the existing
    // POST /api/rooms endpoint (already used server-side by other flows).
    async function createRoom() {
        const displayName = prompt('New room name:');
        if (!displayName) return;
        const trimmed = displayName.trim();
        if (!trimmed) return;

        // The server's `name` field is a URL-safe slug (see CreateRoomRequest
        // pattern ^[a-z0-9-]+$) distinct from the human-facing display_name.
        const slug = trimmed.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
        if (!slug) {
            alert('Room name needs at least one letter or number.');
            return;
        }

        const token = getToken();
        try {
            const res = await fetch('/api/rooms', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ name: slug, display_name: trimmed, is_dm: false }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                alert(`Failed to create room: ${err.detail || res.status}`);
                return;
            }
            const room = await res.json();
            if (!rooms.find(r => r.id === room.id)) {
                rooms.push(room);
                renderRooms();
            }
            selectRoom(room.id);
        } catch (e) {
            alert(`Failed to create room: ${e.message}`);
        }
    }

    function appendMessage(msg) {
        const list = $('message-list');
        list.appendChild(createMessageEl(msg));
        trackOldest(msg.room_id, msg.id);
    }

    function appendSystemMessage(text) {
        const el = document.createElement('div');
        el.className = 'system-message';
        el.textContent = text;
        $('message-list').appendChild(el);
        if (userAtBottom) scrollToBottom();
    }

    function createMessageEl(msg) {
        const el = document.createElement('div');
        el.className = 'message-row';
        el.dataset.id = msg.id;

        const time = formatTime(msg.created_at);
        const isMe = currentUser && msg.username === currentUser.username;
        const isBot = users.some(u => u.username === msg.username && u.is_bot);
        const authorClass = isMe ? 'self' : (isBot ? 'entity' : 'human');

        // Resolve display name using any nickname the current user has set
        const msgUser = users.find(u => u.username === msg.username);
        const resolvedAuthor = msgUser ? resolveDisplayName(msgUser) : msg.display_name;

        el.dataset.time = time;
        el.dataset.author = resolvedAuthor;
        el.dataset.content = msg.content;

        // Caption: empty/whitespace + image present means the image IS the message.
        // Don't render an empty paragraph stub.
        const hasImage = !!msg.image_url;
        const captionText = (msg.content || '').trim();
        const captionHtml = (hasImage && !captionText) ? '' :
            `<div class="message-content">${parseMarkdown(msg.content || '')}</div>`;
        const imageHtml = hasImage ?
            `<div class="message-image-wrap"><img class="message-image" src="${escapeHtml(msg.image_url)}" alt="shared image" loading="lazy"></div>` : '';

        el.innerHTML = `
            <span class="msg-time">${time}</span>
            <span class="msg-author ${authorClass}">${escapeHtml(resolvedAuthor)}</span>
            ${captionHtml}
            ${imageHtml}
            <button class="copy-btn" title="Copy message" aria-label="Copy message">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
            </button>
        `;

        el.querySelector('.copy-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            copyToClipboard(e.currentTarget, msg.content);
        });

        const imgEl = el.querySelector('.message-image');
        if (imgEl) {
            imgEl.addEventListener('click', () => openLightbox(msg.image_url));
        }

        return el;
    }

    // --- Lightbox ---

    function openLightbox(url) {
        // Prevent stacking — only one lightbox at a time.
        if (document.querySelector('.lightbox-overlay')) return;

        const overlay = document.createElement('div');
        overlay.className = 'lightbox-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-label', 'Image preview');
        overlay.innerHTML = `
            <button class="lightbox-close" aria-label="Close image preview">&times;</button>
            <img class="lightbox-image" src="${escapeHtml(url)}" alt="shared image">
        `;

        // Lock body scroll while open (prevents iOS Safari bounce-scroll behind overlay).
        const prevOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';

        const close = () => {
            overlay.remove();
            document.body.style.overflow = prevOverflow;
            document.removeEventListener('keydown', onKey);
        };

        const onKey = (e) => {
            if (e.key === 'Escape') close();
        };

        // Click outside image (overlay backdrop) closes.
        // Click on image itself does NOT close — lets users tap to inspect.
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) close();
        });
        overlay.querySelector('.lightbox-close').addEventListener('click', close);
        // Tapping the image also closes (parity with most photo viewers; iPad-friendly).
        overlay.querySelector('.lightbox-image').addEventListener('click', close);

        document.addEventListener('keydown', onKey);
        document.body.appendChild(overlay);
    }

    function copyToClipboard(btn, text) {
        const checkSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>`;
        const copySvg = btn.innerHTML;

        const showDone = () => {
            btn.innerHTML = checkSvg;
            btn.classList.add('copied');
            setTimeout(() => {
                btn.innerHTML = copySvg;
                btn.classList.remove('copied');
            }, 1500);
        };

        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(showDone).catch(() => fallbackCopy(text, showDone));
        } else {
            fallbackCopy(text, showDone);
        }
    }

    function fallbackCopy(text, onDone) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); onDone(); } catch (_) {}
        document.body.removeChild(ta);
    }

    function updateTypingIndicator() {
        const list = $('message-list');
        // Remove all existing typing rows
        list.querySelectorAll('.typing-row').forEach(el => el.remove());

        const roomTyping = typingUsers[currentRoomId] || {};
        const names = Object.keys(roomTyping);

        if (names.length > 0) {
            names.forEach(name => {
                const el = document.createElement('div');
                el.className = 'typing-row';
                el.dataset.typingUser = name;
                const isBot = users.some(u => u.username === name && u.is_bot);
                const authorClass = isBot ? 'entity' : 'human';
                // Find display name, applying nickname if set
                const user = users.find(u => u.username === name);
                const displayName = user ? resolveDisplayName(user) : name;

                el.innerHTML = `
                    <span class="msg-time"></span>
                    <span class="msg-author ${authorClass}">${escapeHtml(displayName)}</span>
                    <div class="typing-dots"><span></span><span></span><span></span></div>
                `;
                list.appendChild(el);
            });
            // Only auto-scroll for typing indicators if user is already at the
            // bottom — same policy as new messages (#284).
            if (userAtBottom) scrollToBottom();
        }
    }

    // --- Room switching ---

    async function renameCurrentRoom() {
        if (!currentRoomId) return;
        const room = rooms.find(r => r.id === currentRoomId);
        if (!room) return;
        const token = getToken();

        if (room.is_dm) {
            // For DMs: set a nickname for the OTHER person
            const other = dmOtherUser(room);
            if (!other) return;
            const current = nicknames[other.id] || '';
            const input = prompt(`Nickname for ${other.display_name} (@${other.username}):\n(leave blank to clear)`, current);
            if (input === null) return;

            try {
                if (input.trim() === '') {
                    const res = await fetch(`/api/nicknames/${other.id}`, {
                        method: 'DELETE',
                        headers: { 'Authorization': `Bearer ${token}` },
                    });
                    if (res.ok) delete nicknames[other.id];
                } else {
                    const res = await fetch(`/api/nicknames/${other.id}`, {
                        method: 'PUT',
                        headers: {
                            'Authorization': `Bearer ${token}`,
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ nickname: input.trim() }),
                    });
                    if (res.ok) nicknames[other.id] = input.trim();
                }
                // Update header and re-render
                $('room-name').textContent = roomDisplayLabel(room);
                renderRooms();
                renderUsers();
            } catch (e) {
                console.error('[Haven] DM rename failed:', e);
            }
        } else {
            // For shared rooms: rename globally via PATCH
            const input = prompt('New room name:', room.display_name);
            if (input === null) return;
            const trimmed = input.trim();
            if (!trimmed) return;

            try {
                const res = await fetch(`/api/rooms/${currentRoomId}`, {
                    method: 'PATCH',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ display_name: trimmed }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    alert(`Failed to rename: ${err.detail || res.status}`);
                    return;
                }
                // Optimistic update (WS event also arrives for other members)
                room.display_name = trimmed;
                $('room-name').textContent = roomDisplayLabel(room);
                renderRooms();
            } catch (e) {
                console.error('[Haven] room rename failed:', e);
            }
        }
    }

    function selectRoom(roomId) {
        currentRoomId = roomId;
        saveCurrentRoomId(roomId);  // durable across reloads — see #318
        const room = rooms.find(r => r.id === roomId);
        $('room-name').textContent = room ? roomDisplayLabel(room) : '';
        // Show rename button whenever a room is selected
        const renameBtn = $('rename-room-btn');
        if (renameBtn) renameBtn.style.display = room ? '' : 'none';
        loadRoomMembers(roomId);  // #319: populate the "Current Room" panel

        // Clear unread for this room (locally + persist the read marker server-side)
        delete unread[roomId];
        send({ type: 'read', room_id: roomId });
        updateTitle();
        renderRooms();

        // Clear messages and load history
        $('message-list').innerHTML = '';
        oldestMessageId[roomId] = undefined;
        hasMore[roomId] = false;
        $('load-more').classList.add('hidden');
        // Entering a room — anchor at bottom so first batch of history scrolls down.
        userAtBottom = true;

        send({ type: 'history', room_id: roomId, limit: 50 });

        $('message-input').focus();
    }

    function loadMore() {
        if (!currentRoomId) return;
        const oldest = oldestMessageId[currentRoomId];
        if (oldest) {
            send({ type: 'history', room_id: currentRoomId, before_id: oldest, limit: 50 });
        }
    }

    // --- Input handling ---

    let pendingImage = null;

    function setPendingImage(file) {
        pendingImage = file;
        const wrap = $('image-preview');
        const img = $('image-preview-img');
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => { img.src = e.target.result; };
            reader.readAsDataURL(file);
            wrap.classList.remove('hidden');
        } else {
            img.src = '';
            wrap.classList.add('hidden');
            $('image-input').value = '';
        }
    }

    async function uploadPendingImage(caption) {
        if (!pendingImage || !currentRoomId) return false;
        const room = rooms.find(r => r.id === currentRoomId);
        if (!room) return false;

        const fd = new FormData();
        fd.append('image', pendingImage);
        fd.append('room', room.name);
        if (caption) fd.append('caption', caption);

        const file = pendingImage;
        setPendingImage(null);

        try {
            const resp = await fetch('/api/share-image', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + getToken() },
            body: fd,
        });
            if (!resp.ok) {
                const err = await resp.text();
                alert(`Image upload failed: ${resp.status} ${err}`);
                setPendingImage(file); // restore so user can retry/clear
                return false;
            }
            return true;
        } catch (e) {
            alert(`Image upload failed: ${e.message}`);
            setPendingImage(file);
            return false;
        }
    }

    function initInput() {
        const input = $('message-input');
        const sendBtn = $('send-btn');
        const attachBtn = $('attach-btn');
        const fileInput = $('image-input');
        const previewClear = $('image-preview-clear');
        const inputWrap = document.querySelector('.chat-input');

        const doSend = async () => {
            const content = input.value.trim();
            if (!currentRoomId) return;

            if (pendingImage) {
                await uploadPendingImage(content);
                input.value = '';
                input.style.height = 'auto';
                return;
            }

            if (!content) return;
            send({ type: 'message', room_id: currentRoomId, content });
            input.value = '';
            input.style.height = 'auto';
        };

        sendBtn.addEventListener('click', doSend);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                doSend();
            }
        });

        attachBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files && e.target.files[0];
            if (file) setPendingImage(file);
        });
        previewClear.addEventListener('click', () => setPendingImage(null));

        // Paste image (e.g. screenshot from clipboard)
        input.addEventListener('paste', (e) => {
            const items = e.clipboardData && e.clipboardData.items;
            if (!items) return;
            for (const item of items) {
                if (item.type && item.type.startsWith('image/')) {
                    const file = item.getAsFile();
                    if (file) {
                        e.preventDefault();
                        setPendingImage(file);
                        return;
                    }
                }
            }
        });

        // Drag-and-drop into the chat input area
        const onDragOver = (e) => {
            if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {
                e.preventDefault();
                inputWrap.classList.add('drag-over');
            }
        };
        const onDragLeave = () => inputWrap.classList.remove('drag-over');
        const onDrop = (e) => {
            inputWrap.classList.remove('drag-over');
            const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
            if (file && file.type.startsWith('image/')) {
                e.preventDefault();
                setPendingImage(file);
            }
        };
        inputWrap.addEventListener('dragover', onDragOver);
        inputWrap.addEventListener('dragleave', onDragLeave);
        inputWrap.addEventListener('drop', onDrop);

        // Auto-resize textarea and send typing indicator
        input.addEventListener('input', () => {
            // Resize to fit content, capped at ~5 rows (120px)
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 120) + 'px';

            if (!currentRoomId) return;
            if (!typingTimer) {
                send({ type: 'typing', room_id: currentRoomId });
            }
            clearTimeout(typingTimer);
            typingTimer = setTimeout(() => { typingTimer = null; }, 2000);
        });
    }

    // --- Utilities ---

    function updateTitle() {
        const totalUnread = Object.values(unread).reduce((a, b) => a + b, 0);
        document.title = totalUnread > 0 ? `(${totalUnread}) ${originalTitle}` : originalTitle;
    }

    function scrollToBottom() {
        const container = $('messages');
        container.scrollTop = container.scrollHeight;
        userAtBottom = true;
    }

    function isAtBottom(container) {
        return (container.scrollHeight - container.scrollTop - container.clientHeight) <= SCROLL_BOTTOM_THRESHOLD;
    }

    function initScrollTracking() {
        const container = $('messages');
        if (!container) return;
        container.addEventListener('scroll', () => {
            userAtBottom = isAtBottom(container);
        }, { passive: true });
    }

    function initVisibilityHandlers() {
        document.addEventListener('visibilitychange', () => {
            // Report the change immediately (hidden => inactive => push-eligible;
            // visible => active). We do NOT tear down the socket — the server
            // uses our active/idle report, so real-time delivery stays ready.
            sendActive();
            if (document.visibilityState === 'visible') {
                markActivity();       // returning to the tab counts as interaction
                reconnectNow();       // iPad Safari etc. may have suspended the WS
                if (userAtBottom) requestAnimationFrame(scrollToBottom);
            }
        });

        // Real interaction resets the idle clock (and re-activates if we'd gone
        // idle). Cheap: markActivity only messages the server on a transition.
        ['mousedown', 'mousemove', 'keydown', 'touchstart', 'scroll', 'focus'].forEach((ev) => {
            window.addEventListener(ev, markActivity, { passive: true });
        });

        // Page is actually being unloaded — a clean teardown here is fine.
        window.addEventListener('pagehide', () => {
            if (ws) { try { ws.close(); } catch (_) {} }
        });

        // Network came back — reconnect immediately, don't wait for backoff.
        window.addEventListener('online', () => {
            reconnectNow();
        });
    }

    function trackOldest(roomId, msgId) {
        if (!oldestMessageId[roomId] || msgId < oldestMessageId[roomId]) {
            oldestMessageId[roomId] = msgId;
        }
    }

    function formatTime(isoStr) {
        if (!isoStr) return '';
        try {
            // Normalize space→T (SQLite CURRENT_TIMESTAMP), strip +HH:MM offset before treating as UTC
            const normalized = isoStr.replace(' ', 'T').replace(/[+-]\d{2}:\d{2}$/, 'Z');
            const d = new Date(normalized.endsWith('Z') ? normalized : normalized + 'Z');
            if (isNaN(d.getTime())) return '';
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch {
            return '';
        }
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // Render markdown and ensure all links open in a new tab so Haven
    // stays intact when users click URLs (#291).
    function parseMarkdown(text) {
        const html = marked.parse(text);
        return html.replace(/<a\s/g, '<a target="_blank" rel="noopener noreferrer" ');
    }

    function showLogin(error) {
        $('login-screen').classList.remove('hidden');
        $('chat-app').classList.add('hidden');
        if (error) {
            const el = $('login-error');
            el.textContent = error;
            el.classList.remove('hidden');
        }
    }

    // --- Invite / Leave ---

    async function inviteToRoom() {
        if (!currentRoomId) return;
        const token = getToken();

        // Fetch current members
        const membersRes = await fetch(`/api/rooms/${currentRoomId}/members`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!membersRes.ok) return;
        const { members } = await membersRes.json();
        const memberIds = new Set(members.map(m => m.id));

        // Show non-members
        const nonMembers = users.filter(u => !memberIds.has(u.id));
        if (nonMembers.length === 0) {
            alert('Everyone is already in this room.');
            return;
        }

        const names = nonMembers.map((u, i) => `${i + 1}. ${u.display_name} (${u.username})`).join('\n');
        const input = prompt(`Invite to room:\n${names}\n\nEnter number:`);
        if (!input) return;
        const idx = parseInt(input) - 1;
        if (idx < 0 || idx >= nonMembers.length) return;

        const target = nonMembers[idx];
        const res = await fetch(`/api/rooms/${currentRoomId}/invite`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: target.id })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            alert(`Failed to invite: ${err.detail || res.status}`);
        }
    }

    async function leaveRoom() {
        if (!currentRoomId) return;
        const room = rooms.find(r => r.id === currentRoomId);

        // DMs: "close" just hides from sidebar — does NOT remove membership (#286).
        // Leaving a DM would DELETE the room_members row, causing a UNIQUE
        // constraint violation on re-open (the room name already exists but
        // membership is gone → create branch fails).  Client-side hide is the
        // right semantic: the DM history persists and reopens via name-click.
        if (room && room.is_dm) {
            const closedId = currentRoomId;
            rooms = rooms.filter(r => r.id !== closedId);
            currentRoomId = null;
            $('room-name').textContent = '';
            $('message-list').innerHTML = '';
            renderRooms();
            if (rooms.length > 0) selectRoom(rooms[0].id);
            else { saveCurrentRoomId(null); roomMembers = []; renderRoomUsers(); }
            return;
        }

        if (!confirm(`Leave "${room ? room.display_name : 'this room'}"?`)) return;

        const res = await fetch(`/api/rooms/${currentRoomId}/leave`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            alert(`Failed to leave: ${err.detail || res.status}`);
        }
        // UI update happens via member_left WebSocket event
    }

    // --- Export ---

    function clearConversation() {
        // Clear the rendered message list (UI only — server messages unchanged).
        // User can reload older messages via the "Load older messages" button. (GH#263)
        if (!currentRoomId) return;
        const list = $('message-list');
        if (list) list.innerHTML = '';
        const loadMore = $('load-more');
        if (loadMore) loadMore.classList.add('hidden');
        // Reset the oldest-message cursor for this room so "load more" reloads from the live end
        if (currentRoomId) delete oldestMessageId[currentRoomId];
    }

    function exportConversation() {
        const room = rooms.find(r => r.id === currentRoomId);
        const roomLabel = room ? (room.is_dm ? room.display_name : `#${room.display_name}`) : 'Haven';

        const rows = document.querySelectorAll('#message-list .message-row');
        const lines = [
            `# ${roomLabel}`,
            `*Exported ${new Date().toLocaleString()}*`,
            '',
        ];

        rows.forEach(row => {
            const { time, author, content } = row.dataset;
            if (author && content) {
                lines.push(`**[${time}] ${author}**: ${content}`);
            }
        });

        const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const dateStr = new Date().toISOString().split('T')[0];
        const slug = (room?.display_name || 'chat').toLowerCase().replace(/[^a-z0-9]+/g, '-');
        a.download = `haven-${slug}-${dateStr}.md`;
        a.click();
        URL.revokeObjectURL(url);
    }

    // --- Push notifications ---

    // Converts a URL-safe base64 string (VAPID public key) to a Uint8Array
    // that the browser's pushManager.subscribe() API expects.
    function _urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = atob(base64);
        return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
    }

    // True once we've successfully registered a subscription this session,
    // so the button state stays consistent without re-fetching.
    let _pushSubscribed = false;

    async function enableNotifications({ verbose = false } = {}) {
        // When verbose (a real button tap), surface every failure ON-SCREEN — a
        // phone has no dev console, so a silent console.error is why push bugs
        // stay invisible. An alert lets the user read the exact cause back to us.
        const report = (msg) => {
            console.error('[Haven] push:', msg);
            if (verbose) alert('Notifications: ' + msg);
        };

        // Guard: push requires a service worker registration.
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
            report('not supported in this browser.');
            return;
        }

        // Step 1: request permission — browsers REQUIRE this to follow a user
        // gesture the first time, which is why we never auto-prompt on load.
        // Resolves instantly when already granted.
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            report('permission not granted (' + permission + ').');
            return;
        }

        // Step 2: fetch the VAPID public key from the server.
        // If the server returns 503, push is not configured — hide the button.
        let vapidKey;
        try {
            const res = await fetch('/api/push/vapid-public-key');
            if (res.status === 503) {
                const btn = $('push-notify-btn');
                if (btn) btn.style.display = 'none';
                return;
            }
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const json = await res.json();
            vapidKey = json.publicKey;
        } catch (e) {
            report('could not fetch the server key — ' + e.message);
            return;
        }

        // Step 3: create the PushSubscription via the service worker. FIRST clear
        // any stale subscription: if the SW already holds one made with a DIFFERENT
        // VAPID key (a leftover from an earlier build), the browser throws
        // InvalidStateError and refuses a new one until the old is unsubscribed.
        // That is the single most common "key fetched, then nothing happens" bug,
        // so we always start clean.
        let subscription;
        try {
            const registration = await navigator.serviceWorker.ready;
            const existing = await registration.pushManager.getSubscription();
            if (existing) {
                await existing.unsubscribe();
            }
            subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: _urlBase64ToUint8Array(vapidKey),
            });
        } catch (e) {
            report('the browser refused the subscription — ' + e.name + ': ' + e.message);
            return;
        }

        // Step 4: POST the subscription JSON to the server, authenticated with
        // the same Bearer token the rest of the app uses.
        try {
            const subJson = subscription.toJSON();
            const token = getToken();
            const res = await fetch('/api/push/subscribe', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    endpoint: subJson.endpoint,
                    keys: {
                        p256dh: subJson.keys.p256dh,
                        auth: subJson.keys.auth,
                    },
                }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (e) {
            report('the server rejected the subscription — ' + e.message);
            return;
        }

        _pushSubscribed = true;
        _updatePushButton();
        console.log('[Haven] push: notifications enabled');
        if (verbose) alert('Notifications enabled! 🔔');
    }

    function _updatePushButton() {
        const btn = $('push-notify-btn');
        if (!btn) return;
        // Only reflect "on" once we've ACTUALLY registered a subscription. Do NOT
        // disable merely because OS permission is granted — a user who granted
        // permission before ever registering (e.g. via system settings) would
        // otherwise be locked out of the subscribe flow behind a dead button.
        if (_pushSubscribed) {
            btn.textContent = 'Notifications on';
            btn.disabled = true;
        } else {
            btn.textContent = 'Enable notifications';
            btn.disabled = false;
        }
    }

    async function initPushNotifications() {
        // Only show the button if the browser supports push at all.
        if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
            const btn = $('push-notify-btn');
            if (btn) btn.style.display = 'none';
            return;
        }

        // Check if the server has push configured — hide button if not.
        try {
            const res = await fetch('/api/push/vapid-public-key');
            if (res.status === 503) {
                const btn = $('push-notify-btn');
                if (btn) btn.style.display = 'none';
                return;
            }
        } catch (_) {
            // Network error — leave button visible so user can try
        }

        // Reflect current state on the button (enabled until we've subscribed).
        _updatePushButton();

        const btn = $('push-notify-btn');
        if (btn) {
            // Verbose on a real tap: any failure pops an on-screen alert the user
            // can read back to us (no dev console on a phone).
            btn.addEventListener('click', () => enableNotifications({ verbose: true }));
        }

        // Auto-heal: if permission is already granted (returning user, or granted
        // via OS settings before ever tapping the button), register/refresh the
        // subscription now — no tap needed. requestPermission() resolves instantly
        // when already granted, and pushManager.subscribe() needs no user gesture
        // in that state, so this is safe to run on load.
        if (Notification.permission === 'granted') {
            enableNotifications();
        }
    }

    // Mobile: the sidebar is an off-canvas drawer. The hamburger toggles it; the
    // backdrop and picking a room close it. No-ops on desktop (toggle is hidden).
    function initSidebarDrawer() {
        const app = $('chat-app');
        const toggle = $('sidebar-toggle');
        const backdrop = $('sidebar-backdrop');
        const sidebar = $('sidebar');
        if (!app || !toggle) return;
        const close = () => app.classList.remove('drawer-open');
        toggle.addEventListener('click', () => app.classList.toggle('drawer-open'));
        if (backdrop) backdrop.addEventListener('click', close);
        // Close after tapping a room/DM so the conversation is visible right away.
        if (sidebar) sidebar.addEventListener('click', (e) => {
            if (e.target.closest('.room-item')) close();
        });
    }

    // --- Init ---

    // Notification deep-link: the service worker postMessages the room to open
    // when a notification is tapped on an already-running tab. If we're not
    // connected yet (cold open), stash it for onConnected to apply.
    function initDeepLink() {
        if (!('serviceWorker' in navigator)) return;
        navigator.serviceWorker.addEventListener('message', (e) => {
            const d = e.data || {};
            if (d.type === 'navigate' && d.room_id) {
                if (currentUser && rooms.some(r => r.id === d.room_id)) {
                    selectRoom(d.room_id);
                    $('chat-app').classList.remove('drawer-open');
                } else {
                    pendingRoomId = d.room_id;
                }
            }
        });
    }

    function init() {
        initLogin();
        initInput();
        initScrollTracking();
        initVisibilityHandlers();
        initPushNotifications();
        initSidebarDrawer();
        initDeepLink();
    }

    document.addEventListener('DOMContentLoaded', init);

    return { loadMore, selectRoom, inviteToRoom, leaveRoom, exportConversation, clearConversation, enableNotifications, createRoom, renameCurrentRoom };
})();

// --- PWA: register the (minimal, safe) service worker ---
// The worker only provides an offline fallback for navigations; it never
// caches the app shell, so registering it cannot make Haven serve stale UI.
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch((err) => {
            console.warn('[Haven] service worker registration failed:', err);
        });
    });
}
