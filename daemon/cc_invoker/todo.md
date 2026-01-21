# CC Invoker - Status

## ✅ COMPLETED (2026-01-20)

Built a working CC SDK invoker that provides:
- ✅ Persistent CC connection (~12s one-time startup)
- ✅ Fast subsequent queries (~0.6s vs ~20s cold start)
- ✅ MCP server initialization and readiness checks
- ✅ Clean shutdown
- ✅ Portable: stdio transport means PPS auto-starts as child process

### Files Created
- `invoker.py` - Main ClaudeInvoker class with async interface
- `test_invoker.py` - Basic test (hello + follow-up)
- `test_debug.py` - Debug harness with detailed logging
- `test_mcp.py` - MCP tools test (ambient_recall verification)

### Test Results
- ✅ All tests pass
- ✅ MCP tools work (ambient_recall returns data)
- ✅ First query: ~12s (SDK init + MCP startup)
- ✅ Follow-up queries: ~0.6s (persistent connection)
- ✅ 20x speedup vs cold start

## 📋 NEXT STEPS (For Jeff)

1. **Wire into Discord daemon** - Replace subprocess.run with ClaudeInvoker
   - One invoker per Discord channel (persistent sessions)
   - Reuse connection across messages for low latency
   - Handle reconnects gracefully

2. **Consider context management** (optional enhancement)
   - Track rough context size (word count)
   - Start fresh session when approaching limit
   - For now: rely on SDK's automatic context management

3. **Production testing**
   - Run Discord daemon with new invoker
   - Monitor latency and reliability
   - Verify MCP tools work in production context

## 📚 References
- SDK docs: /docs/reference/Keeping Claude Code CLI Persistent for Low-Latency Interactive Use.md
- Full SDK: https://github.com/anthropics/claude-agent-sdk
- Related issue: #103 (MCP stdio servers in subprocess)
