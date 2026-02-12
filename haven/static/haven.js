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
    let typingTimer = null;
    let typingUsers = {};  // room_id -> {username -> timeout}
    let oldestMessageId = {};  // room_id -> oldest message id loaded
    let hasMore = {};  // room_id -> bool

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
        const tokenInput = $('token-input');
        const loginBtn = $('login-btn');
        const loginError = $('login-error');

        const doLogin = () => {
            const token = tokenInput.value.trim();
            if (!token) return;
            setToken(token);
            loginError.classList.add('hidden');
            connect();
        };

        loginBtn.addEventListener('click', doLogin);
        tokenInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') doLogin();
        });

        // Auto-connect if token saved
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

        ws = new WebSocket(url);

        ws.onopen = () => {
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
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
            // Reconnect
            if (!reconnectTimer) {
                reconnectTimer = setTimeout(() => {
                    reconnectTimer = null;
                    connect();
                }, 3000);
            }
        };

        ws.onerror = () => {};
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
        }
    }

    function onConnected(data) {
        currentUser = data.user;
        rooms = data.rooms;
        users = data.users;

        $('login-screen').classList.add('hidden');
        $('chat-app').classList.remove('hidden');
        $('current-user').textContent = currentUser.display_name;

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
        if (data.room_id === currentRoomId) {
            appendMessage(data);
            scrollToBottom();
        }
        // Could add unread indicators here
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

        hasMore[data.room_id] = data.has_more;
        $('load-more').classList.toggle('hidden', !data.has_more);

        // Maintain scroll position
        const messages = $('messages');
        messages.scrollTop += list.scrollHeight - prevHeight;
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

        if (!typingUsers[data.room_id]) typingUsers[data.room_id] = {};
        clearTimeout(typingUsers[data.room_id][data.username]);
        typingUsers[data.room_id][data.username] = setTimeout(() => {
            delete typingUsers[data.room_id][data.username];
            updateTypingIndicator();
        }, 3000);
        updateTypingIndicator();
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
            el.textContent = (r.is_dm ? '' : '# ') + r.display_name;
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
            el.innerHTML = `
                <span class="status-dot ${u.online ? 'online' : 'offline'}"></span>
                <span>${escapeHtml(u.display_name)}</span>
            `;
            list.appendChild(el);
        });
    }

    function appendMessage(msg) {
        const list = $('message-list');
        list.appendChild(createMessageEl(msg));
        trackOldest(msg.room_id, msg.id);
    }

    function createMessageEl(msg) {
        const el = document.createElement('div');
        el.className = 'message-row py-1 px-2 rounded flex gap-3';
        el.dataset.id = msg.id;

        const time = formatTime(msg.created_at);
        const isMe = currentUser && msg.username === currentUser.username;

        el.innerHTML = `
            <span class="text-xs text-gray-600 mt-1 flex-shrink-0 w-14 text-right">${time}</span>
            <span class="font-medium flex-shrink-0 ${isMe ? 'text-blue-400' : 'text-green-400'}">${escapeHtml(msg.display_name)}</span>
            <span class="text-gray-200 break-words min-w-0">${escapeHtml(msg.content)}</span>
        `;
        return el;
    }

    function updateTypingIndicator() {
        const indicator = $('typing-indicator');
        const roomTyping = typingUsers[currentRoomId] || {};
        const names = Object.keys(roomTyping);

        if (names.length === 0) {
            indicator.classList.add('hidden');
        } else {
            indicator.classList.remove('hidden');
            indicator.textContent = names.length === 1
                ? `${names[0]} is typing...`
                : `${names.join(', ')} are typing...`;
        }
    }

    // --- Room switching ---

    function selectRoom(roomId) {
        currentRoomId = roomId;
        const room = rooms.find(r => r.id === roomId);
        $('room-name').textContent = room ? (room.is_dm ? room.display_name : `# ${room.display_name}`) : '';

        renderRooms();

        // Clear messages and load history
        $('message-list').innerHTML = '';
        oldestMessageId[roomId] = undefined;
        hasMore[roomId] = false;
        $('load-more').classList.add('hidden');

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
        };

        sendBtn.addEventListener('click', doSend);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                doSend();
            }
        });

        // Typing indicator
        input.addEventListener('input', () => {
            if (!currentRoomId) return;
            if (!typingTimer) {
                send({ type: 'typing', room_id: currentRoomId });
            }
            clearTimeout(typingTimer);
            typingTimer = setTimeout(() => { typingTimer = null; }, 2000);
        });
    }

    // --- Utilities ---

    function scrollToBottom() {
        const container = $('messages');
        container.scrollTop = container.scrollHeight;
    }

    function trackOldest(roomId, msgId) {
        if (!oldestMessageId[roomId] || msgId < oldestMessageId[roomId]) {
            oldestMessageId[roomId] = msgId;
        }
    }

    function formatTime(isoStr) {
        try {
            const d = new Date(isoStr + (isoStr.endsWith('Z') ? '' : 'Z'));
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

    // --- Init ---

    function init() {
        initLogin();
        initInput();
    }

    document.addEventListener('DOMContentLoaded', init);

    return { loadMore, selectRoom };
})();
