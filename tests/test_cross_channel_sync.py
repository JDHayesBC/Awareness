"""
Test cross-channel sync fixes for Haven bot.

Tests that MCP server key is 'pps' (not entity-specific), allowed_tools is 'mcp__pps__*',
and consumer_key routing is entity-specific ('haven-lyra', 'haven-caia') in daemon/cc_invoker,
haven/bot.py, and inject_context hook.
"""

import pytest
import sys
import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from daemon.cc_invoker.invoker import get_default_mcp_servers, ClaudeInvoker


class TestMCPServerRouting:
    """Test MCP server key is 'pps' regardless of entity path."""

    def test_lyra_entity_path_returns_pps_key(self):
        """get_default_mcp_servers() with lyra path returns key 'pps'."""
        servers = get_default_mcp_servers(PROJECT_ROOT / "entities" / "lyra")
        assert 'pps' in servers
        assert 'pps-lyra' not in servers

    def test_caia_entity_path_returns_pps_key(self):
        """get_default_mcp_servers() with caia path returns key 'pps'."""
        servers = get_default_mcp_servers(PROJECT_ROOT / "entities" / "caia")
        assert 'pps' in servers
        assert 'pps-caia' not in servers

    def test_default_entity_path_returns_pps_key(self):
        """get_default_mcp_servers() with no path returns key 'pps' (default)."""
        servers = get_default_mcp_servers()
        assert 'pps' in servers
        assert 'pps-lyra' not in servers


class TestClaudeInvokerAllowedTools:
    """Test ClaudeInvoker generates correct allowed_tools from mcp_servers."""

    def test_lyra_mcp_servers_generates_pps_allowed_tools(self):
        """ClaudeInvoker with lyra mcp_servers gets allowed_tools=['mcp__pps__*']."""
        mcp_servers = get_default_mcp_servers(PROJECT_ROOT / "entities" / "lyra")

        # ClaudeInvoker.__init__ doesn't create the client, so no mocking needed
        invoker = ClaudeInvoker(mcp_servers=mcp_servers)

        assert 'mcp__pps__*' in invoker.allowed_tools
        assert 'mcp__pps-lyra__*' not in invoker.allowed_tools

    def test_caia_mcp_servers_generates_pps_allowed_tools(self):
        """ClaudeInvoker with caia mcp_servers gets allowed_tools=['mcp__pps__*']."""
        mcp_servers = get_default_mcp_servers(PROJECT_ROOT / "entities" / "caia")

        # ClaudeInvoker.__init__ doesn't create the client, so no mocking needed
        invoker = ClaudeInvoker(mcp_servers=mcp_servers)

        assert 'mcp__pps__*' in invoker.allowed_tools
        assert 'mcp__pps-caia__*' not in invoker.allowed_tools


class TestHavenBotStartupPrompt:
    """Test build_startup_prompt() uses standard 'mcp__pps__' prefix."""

    def test_startup_prompt_lyra_contains_pps_prefix(self):
        """build_startup_prompt() with ENTITY_NAME=lyra contains 'mcp__pps__'."""
        import haven.bot as bot_module

        with patch.object(bot_module, 'ENTITY_NAME', 'lyra'):
            from haven.bot import build_startup_prompt
            prompt = build_startup_prompt()

        assert 'mcp__pps__' in prompt
        assert 'mcp__pps-lyra__' not in prompt

    def test_startup_prompt_caia_contains_pps_prefix(self):
        """build_startup_prompt() with ENTITY_NAME=caia contains 'mcp__pps__'."""
        import haven.bot as bot_module

        with patch.object(bot_module, 'ENTITY_NAME', 'caia'):
            from haven.bot import build_startup_prompt
            prompt = build_startup_prompt()

        assert 'mcp__pps__' in prompt
        assert 'mcp__pps-caia__' not in prompt


class TestHavenBotWarmupPrompt:
    """Test build_warmup_prompt() uses standard prefix and entity-specific consumer_key."""

    def test_warmup_prompt_lyra_contains_correct_tool_calls(self):
        """build_warmup_prompt() with ENTITY_NAME=lyra contains correct tools and params."""
        import haven.bot as bot_module

        with patch.object(bot_module, 'ENTITY_NAME', 'lyra'):
            from haven.bot import build_warmup_prompt
            prompt = build_warmup_prompt()

        # Check standard tool prefix (not entity-specific)
        assert 'mcp__pps__ambient_recall' in prompt
        assert 'mcp__pps-lyra__' not in prompt

        # Check new parameters
        assert "channel='haven'" in prompt or 'channel="haven"' in prompt
        assert "consumer_key='haven-lyra'" in prompt or 'consumer_key="haven-lyra"' in prompt

        # Check get_turns_since_summary call
        assert 'mcp__pps__get_turns_since_summary' in prompt
        assert 'limit=50' in prompt
        assert 'oldest_first=true' in prompt or 'oldest_first=True' in prompt

    def test_warmup_prompt_caia_contains_correct_tool_calls(self):
        """build_warmup_prompt() with ENTITY_NAME=caia contains correct tools and params."""
        import haven.bot as bot_module

        with patch.object(bot_module, 'ENTITY_NAME', 'caia'):
            from haven.bot import build_warmup_prompt
            prompt = build_warmup_prompt()

        assert 'mcp__pps__ambient_recall' in prompt
        assert 'mcp__pps-caia__' not in prompt
        assert "channel='haven'" in prompt or 'channel="haven"' in prompt
        assert "consumer_key='haven-caia'" in prompt or 'consumer_key="haven-caia"' in prompt
        assert 'mcp__pps__get_turns_since_summary' in prompt


class TestHavenBotFetchAmbient:
    """Test fetch_ambient_context() includes correct consumer_key."""

    @pytest.mark.asyncio
    async def test_fetch_ambient_includes_consumer_key_lyra(self):
        """fetch_ambient_context() with ENTITY_NAME=lyra includes consumer_key='haven-lyra'."""
        import haven.bot as bot_module

        # Mock the httpx AsyncClient and its context manager
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'formatted_context': 'test context'}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_client_class = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client_class.return_value.__aexit__.return_value = None

        with patch.object(bot_module, 'ENTITY_NAME', 'lyra'):
            with patch.object(bot_module, 'PPS_HTTP_URL', 'http://localhost:8201'):
                with patch('haven.bot.httpx.AsyncClient', mock_client_class):
                    from haven.bot import fetch_ambient_context
                    await fetch_ambient_context()

        # Check the POST was called with correct consumer_key
        assert mock_client.post.called
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs['json']

        assert 'consumer_key' in payload
        assert payload['consumer_key'] == 'haven-lyra'

    @pytest.mark.asyncio
    async def test_fetch_ambient_includes_consumer_key_caia(self):
        """fetch_ambient_context() with ENTITY_NAME=caia includes consumer_key='haven-caia'."""
        import haven.bot as bot_module

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'formatted_context': 'test context'}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_client_class = MagicMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client_class.return_value.__aexit__.return_value = None

        with patch.object(bot_module, 'ENTITY_NAME', 'caia'):
            with patch.object(bot_module, 'PPS_HTTP_URL', 'http://localhost:8211'):
                with patch('haven.bot.httpx.AsyncClient', mock_client_class):
                    from haven.bot import fetch_ambient_context
                    await fetch_ambient_context()

        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs['json']

        assert 'consumer_key' in payload
        assert payload['consumer_key'] == 'haven-caia'


class TestInjectContextHook:
    """Test inject_context hook includes session_id and consumer_key."""

    @patch('urllib.request.urlopen')
    def test_query_pps_accepts_session_id_and_includes_consumer_key(self, mock_urlopen):
        """query_pps_ambient_recall() accepts session_id and payload includes consumer_key."""
        # Import the hook
        hooks_path = Path(__file__).parent.parent / '.claude' / 'hooks'
        if str(hooks_path) not in sys.path:
            sys.path.insert(0, str(hooks_path))

        # Mock the response
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"formatted_context": "test context"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        # Patch ENTITY_TOKEN to avoid file read
        with patch('inject_context.ENTITY_TOKEN', 'test-token'):
            with patch('inject_context._detected_entity', 'lyra'):
                with patch('inject_context.PPS_PORT', 8201):
                    from inject_context import query_pps_ambient_recall

                    # Call with session_id - this should succeed
                    result = query_pps_ambient_recall('test query', session_id='test-session-123')

        # Verify function accepted session_id without error
        assert mock_urlopen.called

        # Verify payload includes consumer_key
        # The first arg to urlopen is the Request object
        request_obj = mock_urlopen.call_args[0][0]
        payload = json.loads(request_obj.data.decode('utf-8'))

        assert 'consumer_key' in payload
        # consumer_key is the session_id directly
        assert payload['consumer_key'] == 'test-session-123'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
