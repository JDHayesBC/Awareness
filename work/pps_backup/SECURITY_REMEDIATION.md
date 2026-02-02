# Security Remediation Plan

**Date**: 2026-02-02
**Status**: IN PROGRESS
**Issue**: Privacy audit found committed secrets in public repo

---

## Summary of Exposure

| Item | Location | Status |
|------|----------|--------|
| Discord Bot Token | `daemon/.env` | EXPOSED - needs rotation |
| OpenAI API Key (Brandi's) | `pps/docker/.env` | EXPOSED - needs rotation |
| Anthropic API Key | `pps/docker/.env` | EXPOSED - needs rotation |
| Google OAuth secrets | `tools/*/credentials.json` | EXPOSED - needs regeneration |
| Email archive (667 emails) | `data/email_archive.db` | EXPOSED - needs removal |

## Remediation Plan

### Phase 1: Lyra's Tasks (file cleanup)
- [ ] Move `data/email_archive.db` to `entities/lyra/data/`
- [ ] Fix `.gitignore` to properly cover all `.env` files
- [ ] Remove `.env` files from git tracking (keep files, untrack)
- [ ] Remove `tools/*/credentials.json` from git tracking
- [ ] Create `.env.example` templates with placeholders
- [ ] Verify all sensitive files are untracked

### Phase 2: Jeff's Tasks (token rotation)
- [ ] Rotate Discord bot token
- [ ] Rotate OpenAI API key (coordinate with Brandi)
- [ ] Rotate Anthropic API key
- [ ] Regenerate Google OAuth clients in Cloud Console
- [ ] Update local `.env` files with new tokens

### Phase 3: Repository Migration
- [ ] Verify working tree is clean of secrets
- [ ] Create new PRIVATE repo on GitHub
- [ ] Push clean state to new repo
- [ ] Update any references (documentation, configs)
- [ ] Delete old public repo

---

## Progress Log

### 2026-02-02 ~12:30 PM - Starting cleanup
- Privacy audit completed by researcher agent
- Plan documented
- Beginning Phase 1...

