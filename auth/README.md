# auth

Email-based magic-link authentication for aeratools. Sets a signed JWT session cookie on the root domain so all tools can read it.

## Flow

1. User visits `auth.<ROOT_DOMAIN>/?next=<url>`
2. Enters email → receives a sign-in link (15 min TTL, stored in S3)
3. Clicks link → token validated and deleted from S3, JWT cookie set on `.<ROOT_DOMAIN>`
4. Redirected to `next`

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ROOT_DOMAIN` | yes | e.g. `example.com` — cookie domain and auth URL base |
| `SESSION_SECRET` | yes | Secret key for signing JWTs, shared with all tools that call `get_current_user` |
| `S3_ENDPOINT_URL` | yes | Object store endpoint |
| `AWS_ACCESS_KEY_ID` | yes | Object store key |
| `AWS_SECRET_ACCESS_KEY` | yes | Object store secret |
| `S3_BUCKET` | yes | Bucket for pending tokens (stored under `auth/pending/`) |
| `SENDGRID_API_KEY` | no | If set, uses SendGrid to send email |
| `SMTP_HOST` | no | SMTP hostname (default: `localhost`) |
| `SMTP_PORT` | no | SMTP port (default: `587`) |
| `SMTP_USER` | no | SMTP username |
| `SMTP_PASS` | no | SMTP password |
| `EMAIL_FROM` | no | From address (default: `noreply@<ROOT_DOMAIN>`) |

`SENDGRID_API_KEY` takes priority over SMTP settings. At least one must be configured.

## Using auth in a tool

```python
from auth import get_current_user, require_auth, register_auth_context

# Inject user/auth_url into all templates:
register_auth_context(app)

# Read the current user in a route:
user = get_current_user()  # returns email string or None

# Require login for a whole route:
@app.route("/private")
@require_auth
def private():
    ...
```

The `user` and `auth_url` template variables are available in any template once `register_auth_context` is called.
