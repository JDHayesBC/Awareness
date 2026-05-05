/**
 * Haven — WebSocket chat client
 */
const haven = (() => {
    let ws = null;
    let currentUser = null;
    let currentRoomId = null;
    let rooms = [];
    let users = [];
    let reconnectTimer = null;
    let reconnectAttempt = 0;
    let reconnectingBannerTimer = null;
    let typingTimer = null;
    let typingUsers = {};  // room_id -> {username -> timeout}
    let oldestMessageId = {};  // room_id -> oldest message id loaded
    let hasMore = {};  // room_id -> bool
    let unread = {};  // room_id -> count
    let userAtBottom = true;  // tracks whether scroll is anchored at bottom
    const SCROLL_BOTTOM_THRESHOLD = 120;  // px from bottom to count as "at bottom"
    const originalTitle = document.title;

    const $ = (id) => document.getElementById(id);

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

    // --- Event handlers ---

    function handleEvent(data) {
        switch (data.type) {
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
        }
    }

    function onConnected(data) {
        currentUser = data.user;
        rooms = data.rooms;
        users = data.users;

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

        // Select first room
        if (rooms.length > 0) {
            selectRoom(rooms[0].id);
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
        }
    }

    function onMemberLeft(data) {
        if (data.room_id === currentRoomId) {
            appendSystemMessage(`${escapeHtml(data.username)} left`);
        }
        if (currentUser && data.user_id === currentUser.id) {
            // We left — remove room from sidebar and switch
            rooms = rooms.filter(r => r.id !== data.room_id);
            renderRooms();
            if (currentRoomId === data.room_id) {
                currentRoomId = null;
                $('room-name').textContent = '';
                $('message-list').innerHTML = '';
                if (rooms.length > 0) selectRoom(rooms[0].id);
            }
        }
    }

    // --- Rendering ---

    function renderRooms() {
        const roomList = $('room-list');
        const dmList = $('dm-list');
        roomList.innerHTML = '';
        dmList.innerHTML = '';

        let hasDMs = false;
        rooms.forEach(r => {
            const el = document.createElement('div');
            el.className = 'room-item' + (r.id === currentRoomId ? ' active' : '');

            const label = (r.is_dm ? '' : '# ') + r.display_name;
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

    function renderUsers() {
        const list = $('user-list');
        list.innerHTML = '';

        // Online first, then alphabetical
        const sorted = [...users].sort((a, b) => {
            if (a.online !== b.online) return a.online ? -1 : 1;
            return a.username.localeCompare(b.username);
        });

        sorted.forEach(u => {
            const el = document.createElement('div');
            el.className = 'user-item';
            el.title = `Click to DM @${u.username}`;
            el.innerHTML = `
                <span class="status-dot ${u.online ? 'online' : 'offline'}"></span>
                <span>${escapeHtml(u.display_name)}</span>
                ${u.is_bot ? '<span class="bot-tag">entity</span>' : ''}
            `;
            // Click to start DM
            if (currentUser && u.id !== currentUser.id) {
                el.addEventListener('click', () => startDM(u.username));
            }
            list.appendChild(el);
        });
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

        el.dataset.time = time;
        el.dataset.author = msg.display_name;
        el.dataset.content = msg.content;

        // Caption: empty/whitespace + image present means the image IS the message.
        // Don't render an empty paragraph stub.
        const hasImage = !!msg.image_url;
        const captionText = (msg.content || '').trim();
        const captionHtml = (hasImage && !captionText) ? '' :
            `<div class="message-content">${marked.parse(msg.content || '')}</div>`;
        const imageHtml = hasImage ?
            `<div class="message-image-wrap"><img class="message-image" src="${escapeHtml(msg.image_url)}" alt="shared image" loading="lazy"></div>` : '';

        el.innerHTML = `
            <span class="msg-time">${time}</span>
            <span class="msg-author ${authorClass}">${escapeHtml(msg.display_name)}</span>
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
                // Find display name
                const user = users.find(u => u.username === name);
                const displayName = user ? user.display_name : name;

                el.innerHTML = `
                    <span class="msg-time"></span>
                    <span class="msg-author ${authorClass}">${escapeHtml(displayName)}</span>
                    <div class="typing-dots"><span></span><span></span><span></span></div>
                `;
                list.appendChild(el);
            });
            scrollToBottom();
        }
    }

    // --- Room switching ---

    function selectRoom(roomId) {
        currentRoomId = roomId;
        const room = rooms.find(r => r.id === roomId);
        $('room-name').textContent = room ? (room.is_dm ? room.display_name : `# ${room.display_name}`) : '';

        // Clear unread for this room
        delete unread[roomId];
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

    function initInput() {
        const input = $('message-input');
        const sendBtn = $('send-btn');

        const doSend = () => {
            const content = input.value.trim();
            if (!content || !currentRoomId) return;
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
        // iPad Safari aggressively suspends WS when the tab is backgrounded.
        // When the tab becomes visible again, force a reconnect if needed and
        // re-anchor scroll if the user was at the bottom before.
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState !== 'visible') return;
            if (!ws || ws.readyState !== WebSocket.OPEN) {
                reconnectNow();
            }
            // If they were at the bottom (or this is first foregrounding), scroll
            // them back to bottom so new messages aren't hidden below the fold.
            if (userAtBottom) {
                requestAnimationFrame(scrollToBottom);
            }
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

    // --- Init ---

    function init() {
        initLogin();
        initInput();
        initScrollTracking();
        initVisibilityHandlers();
    }

    document.addEventListener('DOMContentLoaded', init);

    return { loadMore, selectRoom, inviteToRoom, leaveRoom, exportConversation };
})();
