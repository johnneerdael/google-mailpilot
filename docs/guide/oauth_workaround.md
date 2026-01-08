# OAuth Workaround (Unsupported)

> **WARNING**: This configuration is **unsupported** and may break at any time. It relies on reusing public Client IDs from popular open-source applications (Thunderbird, GNOME, Mailspring) which are trusted by Google. We strongly recommend creating your own [GCP Project](configuration.md#step-2-google-cloud-project-setup) if possible.

If you are unable to create a Google Cloud Platform project (e.g., due to organizational restrictions or verification issues), you can attempt to use the public credentials of known open-source email clients.

## OAUTH_MODE: The Key Setting

When using third-party OAuth credentials (Thunderbird, GNOME, etc.), you **must** set `oauth_mode: imap` in your config or set the `OAUTH_MODE=imap` environment variable.

### Why This Matters

Third-party OAuth credentials typically include these scopes:
- ✅ `https://mail.google.com/` - IMAP/SMTP access
- ✅ `https://www.googleapis.com/auth/calendar` - Google Calendar API

But they **do NOT include**:
- ❌ `https://www.googleapis.com/auth/gmail.readonly` - Gmail REST API
- ❌ `https://www.googleapis.com/auth/gmail.modify` - Gmail REST API

This means **Gmail REST API calls will fail** with these credentials. The `oauth_mode: imap` setting tells the server to use IMAP/SMTP protocols instead.

### Mode Comparison

| Feature | `oauth_mode: api` | `oauth_mode: imap` |
|---------|-------------------|---------------------|
| Email search | Gmail REST API | IMAP SEARCH |
| Fetch threads | Gmail REST API | IMAP FETCH |
| Send emails | Gmail REST API | SMTP with XOAUTH2 |
| Calendar | Google Calendar API | Google Calendar API |
| Labels/folders | Gmail labels | IMAP folders |
| Required scopes | gmail.readonly, gmail.modify, calendar | mail.google.com, calendar |
| Best for | Own GCP credentials | Third-party credentials |

## Known Public Credentials

These credentials belong to widely used open-source projects. They are generally whitelisted by Google for broad use.

### Provider Comparison

| Provider | Source | Scopes | Encrypted |
|----------|--------|--------|-----------|
| Mozilla Thunderbird | [OAuth2Providers.sys.mjs](https://github.com/mozilla/releases-comm-central/blob/master/mailnews/base/src/OAuth2Providers.sys.mjs) | mail.google.com, calendar, carddav | No |
| GNOME Online Accounts | [meson_options.txt](https://gitlab.gnome.org/GNOME/gnome-online-accounts/-/blob/master/meson_options.txt) | mail.google.com, calendar, contacts | No |
| Evolution Data Server | [CMakeLists.txt](https://gitlab.gnome.org/GNOME/evolution-data-server/-/blob/master/CMakeLists.txt) | mail.google.com, calendar | No |
| Mailspring | [onboarding-constants.ts](https://github.com/Foundry376/Mailspring/blob/master/app/internal_packages/onboarding/lib/onboarding-constants.ts) | mail.google.com, calendar, contacts | **Yes (AES)** |

---

### Mozilla Thunderbird

**Source**: [OAuth2Providers.sys.mjs](https://github.com/mozilla/releases-comm-central/blob/master/mailnews/base/src/OAuth2Providers.sys.mjs)

```
Client ID:     406964657835-aq8lmia8j95dhl1a2bvharmfk3t1hgqj.apps.googleusercontent.com
Client Secret: kSmqreRr0qwBWJgbf5Y-PjSU
```

**Available Scopes**:
- `https://mail.google.com/` (IMAP/SMTP)
- `https://www.googleapis.com/auth/calendar` (CalDAV)
- `https://www.googleapis.com/auth/carddav` (CardDAV/Contacts)

---

### GNOME Online Accounts

**Source**: [meson_options.txt](https://gitlab.gnome.org/GNOME/gnome-online-accounts/-/blob/master/meson_options.txt)

Search for `google_client_id` and `google_client_secret` in the meson_options.txt file. The values are build-time options.

**Available Scopes**:
- `https://mail.google.com/` (IMAP/SMTP)
- `https://www.googleapis.com/auth/calendar`
- `https://www.google.com/m8/feeds` (Contacts)

---

### Evolution Data Server

**Source**: [CMakeLists.txt](https://gitlab.gnome.org/GNOME/evolution-data-server/-/blob/master/CMakeLists.txt)

Search for `GOOGLE_CLIENT_ID` in the CMakeLists.txt file. Evolution Data Server is the backend for GNOME Evolution mail client.

**Available Scopes**:
- `https://mail.google.com/` (IMAP/SMTP)
- `https://www.googleapis.com/auth/calendar`

---

### Mailspring (Encrypted)

**Source**: [onboarding-constants.ts](https://github.com/Foundry376/Mailspring/blob/master/app/internal_packages/onboarding/lib/onboarding-constants.ts)

Mailspring encrypts its OAuth secrets. You'll need to decrypt them:

```
Client ID: 662287800555-0a5h4ii0e9hil1dims8hn5opk76pce9t.apps.googleusercontent.com
```

**Encrypted Secret** (AES-256-CTR):
```
Ciphertext (base64): 1EyEGYVh3NBNIbYEdpdMvOzCH7+vrSciGeYZ1F+W6W+yShk=
IV (base64):         wgvAx+N05nHqhFxJ9I07jw==
Key:                 don't-be-ev1l-thanks--mailspring
```

**Python Decryption Code**:

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import hashlib

def decrypt_mailspring_secret():
    key = b"don't-be-ev1l-thanks--mailspring"
    # Key must be 32 bytes for AES-256
    key_hash = hashlib.sha256(key).digest()
    
    iv = base64.b64decode("wgvAx+N05nHqhFxJ9I07jw==")
    ciphertext = base64.b64decode("1EyEGYVh3NBNIbYEdpdMvOzCH7+vrSciGeYZ1F+W6W+yShk=")
    
    cipher = Cipher(algorithms.AES(key_hash), modes.CTR(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    
    return plaintext.decode('utf-8')

if __name__ == "__main__":
    print(f"Client Secret: {decrypt_mailspring_secret()}")
```

**Available Scopes**:
- `https://mail.google.com/` (IMAP/SMTP)
- `https://www.googleapis.com/auth/calendar`
- `https://www.googleapis.com/auth/contacts`
- `https://www.googleapis.com/auth/userinfo.email`

---

## How to Use

1. Open your `config.yaml`.
2. **Set oauth_mode to imap** (critical!):

```yaml
oauth_mode: imap

identity:
  email: your-email@gmail.com
  full_name: "Your Name"

imap:
  host: imap.gmail.com
  port: 993
  username: your-email@gmail.com
  use_ssl: true
  oauth2:
    client_id: "<client_id_from_provider>"
    client_secret: "<client_secret_from_provider>"

timezone: America/Los_Angeles
working_hours:
  start: "09:00"
  end: "17:00"
  workdays: [1, 2, 3, 4, 5]
vip_senders: []
```

3. Run the authentication setup:
```bash
uv run auth_setup --mode imap
```

4. When authenticating, you'll see a consent screen for the provider you chose (e.g., "Mozilla Thunderbird"). This is expected.

## Limitations

1. **IMAP Search Limitations**: Gmail's IMAP search is less powerful than the Gmail REST API. Complex queries like `label:important OR from:boss@example.com` may not work exactly as expected.

2. **No Gmail Labels**: In IMAP mode, you work with IMAP folders instead of Gmail labels. The `modify_gmail_labels` tool is not available.

3. **Quota Sharing**: You share the API quota with all other users of that client ID (though usually per-user quotas apply).

4. **Future Blocking**: Google may rotate these secrets or block access at any time.

## Troubleshooting

### "Gmail API scopes not available" Error
Make sure you've set `oauth_mode: imap` in your config.yaml or `OAUTH_MODE=imap` environment variable.

### "Authentication failed" During SMTP Send
Re-run `uv run auth_setup --mode imap` to refresh your tokens.

### Calendar Still Works But Email Doesn't
This confirms you're using third-party credentials. Set `oauth_mode: imap` to fix email operations.

### "Access blocked: This app's request is invalid"
The provider's client ID may have been revoked by Google. Try a different provider from the list above.
