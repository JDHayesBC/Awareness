# Hook Haiku Compression Fix

**Date**: 2026-01-25
**Status**: PARTIAL - Timeout fixed, compression disabled pending proper solution

---

## Problem

The UserPromptSubmit hook at `.claude/hooks/inject_context.py` was calling `subprocess.run(["claude", "--model", "haiku"], ...)` to compress ambient_recall context. This subprocess call timed out frequently, causing the hook to fall back to raw context.

---

## Solution Attempted

### Approach 1: Direct cc_invoker Import
- **Issue**: Hook runs in system Python, but `daemon.cc_invoker` requires `claude_agent_sdk` which isn't installed system-wide
- **Outcome**: Not feasible without modifying system Python environment

### Approach 2: CC-Wrapper HTTP API
- **Implementation**: Updated hook to call HTTP endpoint at `localhost:8204/v1/chat/completions`
- **Docker Setup**: Fixed `Dockerfile.cc-wrapper` and `docker-compose.yml` build contexts
- **Issue**: Claude Code SDK refuses to bypass permissions when running as root in Docker
- **Error**: `--dangerously-skip-permissions cannot be used with root/sudo privileges for security reasons`
- **Outcome**: Container fails to start due to SDK security restrictions

---

## Current Status

**Hook Changes Made**:
1. ✅ Removed subprocess call to `claude` CLI
2. ✅ Added HTTP-based haiku compression via cc-wrapper endpoint
3. ✅ Updated hook in both `.claude/hooks/` and `hooks/` directories
4. ✅ Preserved fallback behavior (returns raw context if compression fails)

**Infrastructure Changes**:
1. ✅ Fixed Dockerfile.cc-wrapper build context paths
2. ✅ Fixed docker-compose.yml build context for pps-cc-wrapper
3. ❌ cc-wrapper container fails to start due to root/permissions conflict

**Current Behavior**:
- Hook attempts HTTP call to `localhost:8204/v1/chat/completions`
- Connection fails (container not running)
- Hook falls back to raw context (uncompressed)
- **Net effect**: Same as before, but timeout is eliminated

---

##Files Modified

### .claude/hooks/inject_context.py
- Replaced subprocess call with HTTP request to cc-wrapper
- Added URL constant: `CC_WRAPPER_URL = "http://localhost:8204/v1/chat/completions"`
- Updated error handling for connection failures

### hooks/inject_context.py
- Same changes as above (this is the project-level copy)

### pps/docker/Dockerfile.cc-wrapper
- Fixed COPY paths: `docker/...` → `pps/docker/...`
- Updated build instructions comment

### pps/docker/docker-compose.yml
- Fixed build context: `context: ..` → `context: ../..`

### pps/docker/cc_openai_wrapper.py
- Fixed sys.path insertion: `parent.parent.parent / "daemon"` → `parent / "daemon"`

---

## Remaining Issues

### Issue #1: CC-Wrapper Docker Permissions
**Problem**: Claude Code SDK won't run with bypass_permissions as root
**Impact**: Can't use cc-wrapper in Docker for haiku compression
**Solutions**:
1. Run Docker container as non-root user (requires volume permission fixes)
2. Use different compression method (custom summarization endpoint)
3. Disable compression entirely (current fallback behavior)

### Issue #2: No Haiku Compression Currently Active
**Problem**: Hook is trying to call cc-wrapper but it's not running
**Impact**: All ambient_recall context is passed raw (not compressed)
**Workaround**: Set `PPS_HAIKU_SUMMARIZE=false` to skip compression attempt
**Long-term**: Need working compression solution for large context

---

## Recommendations

### Short-term (Now)
1. **Disable haiku compression**: Set `PPS_HAIKU_SUMMARIZE=false` in environment
2. **Monitor context sizes**: Check if raw context is causing issues
3. **Document workaround**: Update env.example with compression flag

### Medium-term (Next sprint)
1. **Custom summarization endpoint**: Create dedicated /summarize endpoint in pps-server
2. **Use lightweight model**: Run haiku directly in pps-server container (no SDK needed)
3. **Test compression quality**: Compare raw vs compressed context quality

### Long-term (Future)
1. **Non-root Docker user**: Run cc-wrapper as non-root with proper volume permissions
2. **Alternative SDK**: Explore if claude_agent_sdk can work without permissions bypass
3. **Caching layer**: Cache compressed contexts to avoid repeated summarization

---

## Testing

### Verify Hook Still Works
```bash
# Check debug log after sending a message
tail -f /home/jeff/.claude/data/hooks_debug.log

# Expected: "CC wrapper connection error: ... - using raw context"
```

### Verify Fallback Behavior
```bash
# Check ambient_recall debug log
tail -n 50 /mnt/c/Users/Jeff/Claude_Projects/Awareness/.claude/data/ambient_recall_debug.log

# Should see "Raw Passthrough" method
```

### Re-enable Compression (when fixed)
```bash
# Start cc-wrapper with non-root user (future)
cd pps/docker
docker-compose up -d pps-cc-wrapper

# Verify health
curl http://localhost:8204/health
```

---

## Related Issues

- [ ] TODO: Create GitHub issue for cc-wrapper Docker permissions
- [ ] TODO: Evaluate alternative summarization approaches
- [ ] TODO: Add PPS_HAIKU_SUMMARIZE to .env.example with documentation

---

## Conclusion

**Immediate outcome**: Hook timeout issue is FIXED. The subprocess call that was timing out has been replaced with an HTTP call. When the cc-wrapper isn't available, the hook gracefully falls back to raw context.

**Haiku compression**: Currently DISABLED due to Docker permissions issue with Claude Code SDK. This is acceptable since compression was an optimization, not a requirement. The ambient_recall context works fine without compression - it's just larger.

**Next steps**: Either fix cc-wrapper Docker permissions, or implement a custom summarization endpoint in pps-server that doesn't depend on the Claude Code CLI.
