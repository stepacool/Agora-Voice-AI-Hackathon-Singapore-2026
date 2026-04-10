# Plan: Optional Auth + Memory for AI Therapist

## Overview

Add an optional authentication and session memory layer to the AI Therapist service. This is entirely additive — the existing React clients, backend, and custom LLM continue to work unchanged when auth is not enabled. When enabled, users must authenticate via Google + 2FA before accessing the service, and their session history is encrypted and persisted on disk for continuity across sessions.

All auth endpoints live in the existing simple-backend (Flask). No separate auth service needed.

## Architecture

```
                          AUTH DISABLED (default)
                          ========================
  User → http://localhost:8084?profile=video
       → Client calls GET /auth-check?profile=video → { auth_required: false }
       → Client renders normal UI immediately
       → Backend: anonymous user, no JWT validation
       → Custom LLM: ephemeral, no memory


                          AUTH ENABLED
                          ========================
  User → http://localhost:8084?profile=video_cllm

  Client (on page load, before showing UI):
       → GET /auth-check?profile=video_cllm  (no Bearer token)
       → Backend: AUTH_JWT_SECRET is set for this profile
         → No valid token → 200 { auth_required: true, authenticated: false,
              auth_url: "http://localhost:8082/auth/login?profile=video_cllm
                         &return=http%3A%2F%2Flocalhost%3A8084%3Fprofile%3Dvideo_cllm" }
       → Client: window.location.href = auth_url (immediate redirect)

  Backend Auth Pages (same server, :8082):
       → GET  /auth/login?profile=video_cllm&return=...
              → Stores profile + return URL in Flask session
              → Serves Screen 1: "Sign in with Google" button
       → GET  /auth/google
              → Redirects to Google OAuth (uses GOOGLE_CLIENT_ID from profile)
       → GET  /auth/google/callback
              → Google returns google_sub + email
              → Stores in Flask session, redirects to /auth/identity
       → GET  /auth/identity
              → Serves Screen 2: name + phone + "Send Code" button
       → POST /auth/send-code
              → Reads profile from Flask session to load TWILIO_* + ENCRYPTION_KEY
              → Looks up user by google_sub in data/users/
              → If existing: verifies name_hash + phone_hash match → sends SMS
              → If new: creates profile, stores hashes → sends SMS
              → If mismatch: generic error, no SMS
       → GET  /auth/verify
              → Serves Screen 3: 6-digit PIN entry
       → POST /auth/verify-pin
              → Validates PIN via Twilio Verify API
              → Mints JWT { user_id, email, name, iat, exp }
              → Redirects to: {return_url}&auth_token={jwt}

  Client (page loads again, JWT now in URL):
       → Stores JWT in sessionStorage
       → Strips auth_token from URL via history.replaceState
       → GET /auth-check?profile=video_cllm  (Authorization: Bearer <JWT>)
       → Backend: valid JWT → 200 { auth_required: true, authenticated: true,
                                     user_name: "Jane" }
       → Client: shows normal UI, proceeds as today
       → All subsequent fetch calls include Authorization: Bearer header
       → Backend extracts user_id from JWT on /start-agent
       → Passes user_id to Custom LLM in register-agent params
       → Custom LLM loads encrypted history, injects into prompt
       → On session end: Custom LLM summarizes, encrypts, writes to disk
```

## Components

### 1. Auth Endpoints (NEW routes in `simple-backend/`)

Auth is added as new `/auth/*` routes in the existing Flask backend via a Blueprint. When `AUTH_JWT_SECRET` is not set for a profile, these routes are never reached — the client never redirects to them.

**New file: `core/auth.py`** — self-contained Flask Blueprint (~150 lines). All auth logic lives here, completely isolated from the main `local_server.py`. A new developer doing simple prototyping never sees or touches this file.

**Changes to `local_server.py`** — 3 lines total:
```python
from core.auth import auth_bp, get_authenticated_user_id
app.register_blueprint(auth_bp)
# ... and in /start-agent handler:
user_id, auth_error = get_authenticated_user_id(request, constants)
```

When `AUTH_JWT_SECRET` is not in `.env` (the default), all auth code is inert.

**Routes (all in `core/auth.py` Blueprint):**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/auth-check` | Lightweight check: is auth required for this profile? Is the Bearer token valid? |
| GET | `/auth/login` | Stores `profile` + `return` URL in Flask session. Serves Google sign-in page. |
| GET | `/auth/google` | Redirects to Google OAuth consent screen (uses profile's GOOGLE_CLIENT_ID) |
| GET | `/auth/google/callback` | Handles OAuth response, stores `google_sub` + `email` in Flask session |
| GET | `/auth/identity` | Serves name + phone form |
| POST | `/auth/send-code` | Validates name/phone hashes against stored user profile. Sends Twilio SMS on match. |
| GET | `/auth/verify` | Serves 6-digit PIN entry form |
| POST | `/auth/verify-pin` | Validates PIN via Twilio. Mints JWT. Redirects to `return` URL with `&auth_token=<JWT>` |

**Profile context through the auth flow:**
The `profile` query param is passed to `/auth/login` and stored in Flask session. All subsequent auth routes read it from Flask session to load the correct profile's Google/Twilio/encryption credentials via `initialize_constants(profile)`. This means different profiles can have different Google apps and Twilio accounts.

**HTML pages** — 3 simple server-rendered templates in `simple-backend/templates/auth/`:
```
templates/auth/
  login.html      # "Sign in with Google" button
  identity.html   # Name + phone + "Send Code" button
  verify.html     # 6-digit PIN entry
```

Minimal HTML/CSS, no React. Flask's built-in `render_template` with Jinja2.

**Python dependencies** (add to requirements.txt):
```
PyJWT
google-auth
google-auth-oauthlib
twilio
```

**New `.env` vars (all optional — omit any to disable auth for that profile):**
```env
# Auth config — add to any profile that requires authentication
VIDEO_CLLM_AUTH_JWT_SECRET=a-long-random-secret
VIDEO_CLLM_GOOGLE_CLIENT_ID=...
VIDEO_CLLM_GOOGLE_CLIENT_SECRET=...
VIDEO_CLLM_TWILIO_ACCOUNT_SID=...
VIDEO_CLLM_TWILIO_AUTH_TOKEN=...
VIDEO_CLLM_TWILIO_VERIFY_SERVICE_SID=...
VIDEO_CLLM_ENCRYPTION_KEY=32-byte-hex-master-key
VIDEO_CLLM_AUTH_DATA_DIR=./data
VIDEO_CLLM_MAX_SESSION_DURATION=3600
VIDEO_CLLM_ALLOWED_RETURN_ORIGINS=http://localhost:8084,http://localhost:8083

# Flask session secret (required if auth is enabled — used to sign session cookies
# that persist profile/google_sub through the multi-step auth flow)
FLASK_SECRET_KEY=another-long-random-secret
```

All auth vars are profile-scoped — the same backend can serve auth for one profile and no auth for another. `FLASK_SECRET_KEY` is global (not profile-scoped).

**Google OAuth setup required:**
1. Google Cloud Console → Create project (or use existing)
2. Enable OAuth consent screen (scopes: `email`, `profile`)
3. Create OAuth 2.0 Client ID (Web application)
4. Authorized redirect URI: `http://localhost:8082/auth/google/callback`
5. Provides: `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET`

**Twilio Verify setup required:**
1. Create Twilio account (free trial = $15 credit, ~300 SMS verifications)
2. Dashboard provides: `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN`
3. Verify → Services → Create service (channel: SMS)
4. Provides: `TWILIO_VERIFY_SERVICE_SID`
5. API: `POST /Verifications` (send SMS), `POST /VerificationCheck` (validate PIN)

**Security rules:**
- If returning user: `google_sub` must exist AND `sha256(normalize(name))` must match AND `sha256(normalize(phone))` must match. ALL THREE must pass before Twilio code is even sent.
- Normalization: name → lowercase, trim, collapse whitespace. Phone → strip to digits + leading country code.
- Failure message is always generic: "Unable to verify your identity." No hint about which field failed. No SMS sent on mismatch.
- PIN expires after 5 minutes, max 3 attempts.
- JWT expires after 4 hours (configurable).
- The `return` URL is validated against `ALLOWED_RETURN_ORIGINS` to prevent open redirect attacks.

**User record on disk** (`data/users/{user_id_hash}/profile.enc`):
```json
{
  "google_sub": "118234567890",
  "email": "jane@gmail.com",
  "name_hash": "sha256('jane doe')",
  "phone_hash": "sha256('+14155551234')",
  "created_at": "2026-03-25T11:30:00Z",
  "last_login": "2026-03-25T11:30:00Z"
}
```

`user_id_hash` = `sha256(google_sub)` — used as the directory name and the identity key everywhere downstream. The raw `google_sub` is only in the encrypted profile.

### 2. Backend Auth Validation (in existing `/start-agent`)

`core/auth.py` exports a helper function. The only auth-related change in `local_server.py`:

```python
# In core/auth.py — exported helper
def get_authenticated_user_id(request, constants):
    """Returns (user_id, error). user_id is 'anonymous' when auth not configured."""
    jwt_secret = constants.get("AUTH_JWT_SECRET")
    if not jwt_secret:
        return "anonymous", None
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Authentication required"
    try:
        claims = jwt.decode(auth_header[7:], jwt_secret, algorithms=["HS256"])
        return claims["user_id"], None
    except jwt.InvalidTokenError:
        return None, "Invalid or expired session"

# In local_server.py /start-agent handler — 2 lines added:
user_id, auth_error = get_authenticated_user_id(request, constants)
if auth_error:
    return jsonify({"error": auth_error}), 401
```

Pass `user_id` and `max_session_duration` to the custom LLM via the existing `params` block in the agent payload.

**CORS headers** (needed because client on :8084 sends `Authorization` header to backend on :8082):
```python
# In local_server.py or via flask-cors
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin', '')
    allowed = ['http://localhost:8083', 'http://localhost:8084']  # or from env
    if origin in allowed:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response
```

Note: `Access-Control-Allow-Origin: *` does NOT work with custom `Authorization` headers — the browser requires an explicit origin.

### 3. Custom LLM Changes (`server-custom-llm/node/`)

**Memory module** — new file: `memory_store.js`

**Safety rule: Memory is only written/read when BOTH conditions are met:**
1. `ENCRYPTION_KEY` is set in the custom LLM's `.env`
2. `user_id` received from backend is not `"anonymous"`

If either condition is false, memory is completely skipped — no disk reads, no disk writes, no history injection. The session works exactly as today (ephemeral). This ensures **no sensitive therapy data ever hits disk unencrypted**.

Responsibilities:
- **Load history** on `register-agent` (when `user_id` is not "anonymous" AND `ENCRYPTION_KEY` is set)
- **Inject summary** into system prompt via existing `getSystemInjection` module hook
- **Summarize & save** on `unregister-agent` (same conditions)

**Disk structure:**
```
data/users/{user_id_hash}/
  profile.enc                    # user profile (written by backend auth routes)
  sessions/
    2026-03-25T1130Z.enc         # encrypted session summary (written by custom LLM)
    2026-03-24T0915Z.enc
    ...
```

Both the backend (writes profiles) and custom LLM (writes sessions) access the same `data/` directory. Configure `AUTH_DATA_DIR` in backend and `DATA_DIR` in custom LLM to point to the same path. In production, this could be a shared volume or object storage.

**Encryption:**
- Algorithm: AES-256-GCM
- Per-user key: HKDF(master_key=ENCRYPTION_KEY, info=user_id_hash, salt=random)
- Salt stored as first 16 bytes of each `.enc` file
- Master key in env: `ENCRYPTION_KEY` (same value in both backend and custom LLM `.env`)

**Session summary flow:**

On `unregister-agent`:
1. Get full conversation from `conversation_store.js`
2. Call LLM with summarization prompt:
   ```
   Summarize this therapy session concisely. Note: key topics discussed,
   emotional themes, any breakthroughs or concerns, and anything to
   follow up on in the next session. Keep it under 300 words.
   ```
3. Encrypt the summary with user's derived key
4. Write to `sessions/{timestamp}.enc`

On `register-agent` (with `user_id`):
1. Read all `.enc` files from `data/users/{user_id_hash}/sessions/`
2. Decrypt each with user's derived key
3. Sort by date, take last N sessions (configurable, default 5)
4. Build a context block injected into the system prompt:
   ```
   ## Previous Session History

   Session 1 (March 24, 2026):
   [decrypted summary]

   Session 2 (March 25, 2026):
   [decrypted summary]
   ```

**New env vars (`server-custom-llm/node/.env`):**
```env
ENCRYPTION_KEY=32-byte-hex-master-key
DATA_DIR=./data
MAX_HISTORY_SESSIONS=5
```

### 4. Client Changes (SMALL — auth check on mount + auth header)

The client gains a `useEffect` on mount that calls `/auth-check` and handles the JWT token from URL params. This is a no-op when auth is not configured (backend returns `auth_required: false`).

**On page load** (in main component, e.g. `VideoAvatarClient.tsx`):
```typescript
const [authChecked, setAuthChecked] = useState(false);
const [authUser, setAuthUser] = useState<string | null>(null);

useEffect(() => {
  const checkAuth = async () => {
    // Check if we just returned from auth with a token in URL
    const urlParams = new URLSearchParams(window.location.search);
    let token = urlParams.get('auth_token');
    if (token) {
      // Store in sessionStorage and strip from URL immediately
      sessionStorage.setItem('auth_token', token);
      urlParams.delete('auth_token');
      const cleanUrl = `${window.location.pathname}?${urlParams.toString()}`;
      window.history.replaceState({}, '', cleanUrl);
    } else {
      token = sessionStorage.getItem('auth_token');
    }

    try {
      const currentUrl = window.location.href;
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(
        `${backendUrl}/auth-check?profile=${profile}&return_url=${encodeURIComponent(currentUrl)}`,
        { headers }
      );
      const data = await res.json();

      if (data.auth_required && !data.authenticated) {
        // Not authenticated — redirect to backend auth pages immediately
        window.location.href = data.auth_url;
        return;
      }

      if (data.authenticated) {
        setAuthUser(data.user_name);
      }
    } catch (e) {
      // Backend unreachable — proceed without auth (graceful degradation)
    }
    setAuthChecked(true);
  };
  checkAuth();
}, [backendUrl, profile]);

// Don't render UI until auth check completes
if (!authChecked) return <div>Loading...</div>;
```

**Auth header on all fetch calls:**
```typescript
// Helper — sends Authorization header if token exists, plain fetch otherwise
const fetchWithAuth = (url: string) => {
  const headers: Record<string, string> = {};
  const token = sessionStorage.getItem('auth_token');
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return fetch(url, { headers });
};

// Use everywhere instead of bare fetch():
const tokenResponse = await fetchWithAuth(tokenUrl);
const agentResponse = await fetchWithAuth(agentUrl);
```

When no token is in sessionStorage, this sends a plain request — identical to today's behavior.

**What this looks like to the user:**
- **Auth disabled**: Page loads, brief "Loading..." (milliseconds while /auth-check returns `auth_required: false`), then normal UI. Indistinguishable from today.
- **Auth enabled, not logged in**: Page loads, "Loading...", immediate redirect to backend `/auth/login`. User sees Google sign-in → name/phone → PIN. Gets redirected back with token in URL. Page loads again, token stored, auth check passes, normal UI.
- **Auth enabled, already logged in** (token in sessionStorage, still valid): Page loads, "Loading...", auth check passes, normal UI. No redirect.
- **Token expired**: Auth check returns `authenticated: false`, client clears stale token, redirects to auth flow again.

### 5. Session Duration Limiting

**Custom LLM enforcement (primary):**
- `register-agent` receives `max_session_duration` in params
- Track `registeredAt` per agent (already done in agent registry)
- On each `/chat/completions`, check elapsed time:
  - At 5 minutes before limit: inject into system prompt "Please begin wrapping up the session naturally, we have about 5 minutes remaining."
  - At limit: return a closing message ("Our session time is up for today. Take care.") and call Agora hangup API to end the call

**Backend enforcement (backup):**
- Return `max_duration` in `/start-agent` response body
- Any client that wants to show a countdown timer can read this field
- Existing clients ignore unknown fields — no breakage

## Integration Points

```
Client (on mount)          Backend (:8082)              Custom LLM
─────────────────          ────────────────             ──────────
GET /auth-check ────────→ Check profile config
 + Bearer token (if any)   AUTH_JWT_SECRET set?
                            No → { auth_required: false }
                            Yes + no/bad token → { auth_url: "/auth/login?..." }
                            Yes + valid token → { authenticated: true }

[If redirect to /auth/login needed]
  → /auth/login (same :8082 server)
  → Google OAuth → /auth/google/callback
  → /auth/identity → name/phone form
  → /auth/send-code → Twilio SMS (only if all 3 factors match)
  → /auth/verify → PIN entry
  → /auth/verify-pin → mint JWT, redirect back to client with ?auth_token=<JWT>
  → Client stores JWT in sessionStorage, strips from URL

GET /start-agent ───────→ get_authenticated_user_id()
 + Bearer token             AUTH_JWT_SECRET set? → validate JWT → extract user_id
                            Not set? → user_id = "anonymous"
                            Pass user_id + max_session_duration in params
                            POST /register-agent ────→ Receives user_id
                                                       ENCRYPTION_KEY set + user_id != anonymous?
                                                         Yes → load encrypted history from disk
                                                                inject summaries into system prompt
                                                         No  → skip memory, ephemeral mode

                            POST /unregister-agent ──→ ENCRYPTION_KEY set + user_id != anonymous?
                                                         Yes → summarize conversation via LLM
                                                                encrypt summary
                                                                write to data/users/{hash}/sessions/
                                                         No  → skip, conversation discarded

Shared config:
  Backend .env: AUTH_JWT_SECRET, GOOGLE_*, TWILIO_*, ENCRYPTION_KEY, AUTH_DATA_DIR
  Custom LLM .env: ENCRYPTION_KEY, DATA_DIR (same path as backend's AUTH_DATA_DIR)
  Both: ENCRYPTION_KEY must be identical
```

## File Structure

```
simple-backend/
  local_server.py              # 3 lines added: import, register blueprint, auth check in /start-agent
  core/
    auth.py                    # NEW — Flask Blueprint, all auth routes + helpers (~150 lines)
    agent.py                   # existing, unchanged
    config.py                  # existing, unchanged
    tokens.py                  # existing, unchanged
  templates/
    auth/
      login.html               # NEW — "Sign in with Google" button
      identity.html            # NEW — name + phone + "Send Code"
      verify.html              # NEW — 6-digit PIN entry
  data/                        # NEW — encrypted user data (gitignored)
    users/
      {user_id_hash}/
        profile.enc
        sessions/

server-custom-llm/node/
  memory_store.js              # NEW — encrypted history read/write (~100 lines)
  custom_llm.js                # hooks memory_store into register/unregister agent
  conversation_store.js        # existing, unchanged
```

## What Stays Unchanged

- React client UI layout, components, and connection flow
- Backend `/start-agent`, `/hangup-agent` endpoint signatures and response format
- Custom LLM `/chat/completions` request/response format
- Agora ConvoAI payload structure
- All existing profiles (VIDEO, VOICE, etc.) work without auth when AUTH_JWT_SECRET is not set
- Any client (video, voice, future) can adopt auth by adding the same ~35 line useEffect

## What Changes in Existing Code

| File | Change | Lines |
|------|--------|-------|
| `local_server.py` | Import + register blueprint + auth check in /start-agent + CORS | ~10 |
| `core/auth.py` | NEW file — Blueprint with all auth routes + helpers | ~150 |
| `templates/auth/*.html` | NEW — 3 simple HTML pages | ~50 each |
| `VideoAvatarClient.tsx` | useEffect auth check on mount + fetchWithAuth helper | ~35 |
| `memory_store.js` | NEW file — encrypted history read/write + summarization | ~100 |
| `custom_llm.js` | Hook memory_store into register/unregister agent | ~10 |

## Implementation Order

1. **Backend auth routes** — `core/auth.py` Blueprint, Google OAuth, Twilio 2FA, JWT minting, `/auth-check`, 3 HTML templates
2. **Backend auth validation** — `get_authenticated_user_id()` in `/start-agent`, pass `user_id` to custom LLM, CORS headers
3. **Client auth check** — useEffect + sessionStorage + fetchWithAuth helper
4. **Memory store** — `memory_store.js` in custom LLM, AES-256-GCM encryption, disk read/write, summarization via LLM
5. **Session duration** — elapsed time check in custom LLM, wrap-up prompt injection, Agora hangup on expiry
6. **Integration test** — full flow: client → redirect → auth → redirect back → connect → chat → disconnect → reconnect → verify history loaded

## Security Checklist

- [ ] All three factors (google_sub + name_hash + phone_hash) must match before Twilio SMS is sent
- [ ] Generic error messages — never reveal which factor failed
- [ ] PIN: 5-minute expiry, max 3 attempts, rate limit per phone number
- [ ] JWT: short expiry (4h), stored in sessionStorage (cleared on tab close)
- [ ] JWT stripped from URL immediately via history.replaceState (never visible in browser history)
- [ ] `return` URL validated against ALLOWED_RETURN_ORIGINS allowlist (prevent open redirect)
- [ ] Disk encryption: AES-256-GCM, per-user derived keys via HKDF, random salt per file
- [ ] No PII in logs — user_id_hash only, never name/email/phone in log output
- [ ] Session summaries encrypted at rest — only decrypted by custom LLM with master key
- [ ] user_id_hash (not raw google_sub) used as directory name on disk
- [ ] Memory only written when ENCRYPTION_KEY is set AND user_id is not "anonymous"
- [ ] /auth-check is a read-only GET — no side effects, no token generation
- [ ] Backend rejects /start-agent without valid Bearer token when AUTH_JWT_SECRET is configured
- [ ] FLASK_SECRET_KEY set for signing Flask sessions (persists profile through auth flow)
- [ ] CORS: explicit origin allowlist (not `*`) since Authorization header is used
- [ ] data/ directory added to .gitignore
