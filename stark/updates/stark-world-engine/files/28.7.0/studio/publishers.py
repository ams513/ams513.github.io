"""publishers.py: delivers an APPROVED edit. Refuses to do anything without a valid approval record from the hub.

  python publishers.py --approval .claude/approvals/<session>.json [--no-browser] [--dry-run]
  python publishers.py --setup-wizard [--no-browser]

YouTube   : resumable upload (google-api-python-client, chunks aligned to 256 KB) with YOUR OWN client_secrets.json
            (a free Google Cloud OAuth "Desktop app" client). If client_secrets.json is missing it explains how to
            make one and does nothing else. privacyStatus is forced to "private" whenever a publishAt time is set
            (that is how YouTube schedules); without a time it stays "private" too unless config "yt_privacy" says
            otherwise.
X / Instagram / Substack: free "draft delivery" only - the post text and the media paths are written to
            drafts/<session>/, and the site's own compose page is opened in Chrome. Nothing is posted automatically,
            nothing logs in, no account is created; you do every click.
Setup wizard: opens the official sign-up / developer pages plus a local checklist. You do every step yourself.
AI text   : optional, local only - set "ollama_model" in config.json to draft captions with a local Ollama server
            (http://127.0.0.1:11434). No paid cloud API is used anywhere.
"""
import argparse, datetime, hashlib, hmac, json, os, random, secrets, shutil, subprocess, sys, time, urllib.parse
import urllib.request

from gs_common import APPROVALS, CLIENT_SECRETS, DRAFTS, ROOT, STATE, classroom_mode, get_logger, load_config

CHUNK = 32 * 256 * 1024                    # 8 MiB: a multiple of 256 KiB as the resumable protocol requires
assert CHUNK % (256 * 1024) == 0
SCOPES = ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.readonly']
YT_TOKEN = os.path.join(STATE, 'yt_token.json')
CHROME = [r'C:\Program Files\Google\Chrome\Application\chrome.exe',
          r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe']
log = get_logger('publishers', 'publish.log')

CLIENT_SECRETS_HELP = """client_secrets.json is missing, so nothing was uploaded.
To let Stark World Engine upload to YOUR channel (free; uses the YouTube Data API's free daily quota):
  1. Open https://console.cloud.google.com/ and create a project (any name).
  2. APIs & Services > Library > "YouTube Data API v3" > Enable.
  3. APIs & Services > OAuth consent screen > External > fill in the app name and your e-mail > save, then click
     "Publish app" so the status reads "In production". (Left on "Testing", Google expires the sign-in after
     7 days and uploads stop. "In production" is fine for your own channel; Google only shows an "unverified
     app" warning when you connect: click Advanced > Go to ... (unsafe), it is your own app.)
  4. APIs & Services > Credentials > Create credentials > OAuth client ID > Application type "Desktop app".
  5. Download the JSON and save it as client_secrets.json in this folder (next to publishers.py).
  6. Approve the session again on the hub (or run: python publishers.py --approval <file>).
     The first run opens a Google sign-in page in your browser; the token is stored in .claude/yt_token.json.
Keep client_secrets.json private: it is never included in any release zip."""

WIZARD = [
    ('YouTube: Google Cloud project + YouTube Data API v3', 'https://console.cloud.google.com/apis/library/youtube.googleapis.com'),
    ('YouTube: OAuth client (Desktop app) -> save as client_secrets.json', 'https://console.cloud.google.com/apis/credentials'),
    ('itch.io: create your account', 'https://itch.io/register'),
    ('itch.io: install butler (optional, for uploads)', 'https://itch.io/docs/butler/'),
    ('itch.io: API key for the free stats card', 'https://itch.io/user/settings/api-keys'),
    ('X: sign up (if you do not have an account)', 'https://x.com/i/flow/signup'),
    ('Instagram: sign up (if you do not have an account)', 'https://www.instagram.com/accounts/emailsignup/'),
    ('Substack: start a publication', 'https://substack.com/'),
    ('VDO.Ninja: iPhone camera (no account needed)', 'https://vdo.ninja/'),
]


# ---------------- approval gate ----------------
class NotApproved(Exception):
    pass


def restrict_to_user(path):
    """Windows: limit OUR secret file to the current user (+ SYSTEM) with icacls. Best effort; -> True when applied."""
    user = os.environ.get('USERNAME')
    if os.name != 'nt' or not user or not os.path.exists(path):
        return False
    dom = os.environ.get('USERDOMAIN')
    who = dom + chr(92) + user if dom else user
    try:
        r = subprocess.run(['icacls', path, '/inheritance:r', '/grant:r', f'{who}:F', '/grant:r', '*S-1-5-18:F'],
                           capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def approval_key_path(approvals=APPROVALS):
    """The approval signing key lives next to the approvals folder (.claude/approval.key)."""
    return os.path.join(os.path.dirname(os.path.abspath(approvals)), 'approval.key')


def approval_key(approvals=APPROVALS, create=False):
    """-> 32-byte random secret that signs approval records (never derived from the hub PIN), or None.
    create=True makes it once (exclusive create, user-only file)."""
    path = approval_key_path(approvals)
    for _ in range(2):
        try:
            with open(path, encoding='ascii') as f:
                key = bytes.fromhex(f.read().strip())
            if len(key) >= 32:
                return key
            raise ValueError('approval.key is too short')
        except FileNotFoundError:
            if not create:
                return None
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError:
                continue                        # another process made it first: read theirs
            with os.fdopen(fd, 'w', encoding='ascii') as f:
                f.write(secrets.token_hex(32))
            restrict_to_user(path)
        except ValueError:
            return None
    return None


def sign_approval(rec, key):
    """HMAC-SHA256 over the record (without "token"), keyed with the random approval key."""
    body = {k: v for k, v in rec.items() if k != 'token'}
    return hmac.new(key, json.dumps(body, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def verify_approval(path, cfg=None, approvals=APPROVALS, key=None):
    """-> approval record, or raise NotApproved. The file must live in .claude/approvals and carry the hub's HMAC,
    keyed with the random .claude/approval.key (cfg is unused; kept for callers)."""
    if not path:
        raise NotApproved('no approval record given: approve the session on the Creator Hub first')
    root = os.path.realpath(approvals)
    rp = os.path.realpath(path)
    if not rp.startswith(root + os.sep) or not os.path.isfile(rp):
        raise NotApproved(f'approval record must be a file in {approvals}')
    try:
        with open(rp, encoding='utf-8') as f:
            rec = json.load(f)
    except (OSError, ValueError) as e:
        raise NotApproved(f'approval record unreadable: {e}') from e
    if not isinstance(rec, dict):
        raise NotApproved('approval record unreadable')
    key = key or approval_key(approvals)
    if not key:
        raise NotApproved('no approval key (.claude/approval.key): approve the session on the Creator Hub')
    token = str(rec.pop('token', ''))
    if not hmac.compare_digest(token.encode(), sign_approval(rec, key).encode()):
        raise NotApproved('approval record signature does not match (was it edited by hand?)')
    if not os.path.isfile(rec.get('final', '')):
        raise NotApproved('the approved video file is missing')
    rec['token'] = token
    return rec


# ---------------- text ----------------
def ollama_text(cfg, prompt):
    model = cfg.get('ollama_model')
    if not model:
        return None
    try:
        req = urllib.request.Request('http://127.0.0.1:11434/api/generate', data=json.dumps(
            {'model': model, 'prompt': prompt, 'stream': False}).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r).get('response', '').strip() or None
    except (OSError, ValueError):
        return None


def post_texts(rec, cfg):
    topic = cfg.get('video_topic') or 'New video'
    base = ollama_text(cfg, f'Write one short, upbeat social post (max 200 characters, no hashtags spam) about: {topic}')
    base = base or f'{topic}. New video is up.'
    link = cfg.get('channel_url') or ''
    return {'title': topic[:100],
            'description': f'{topic}\n\nMade with Stark World Engine.\n{link}'.strip(),
            'x': f'{base} {link}'.strip()[:270],
            'instagram': f'{base}\n\n#gamedev #indiegame',
            'substack': f'# {topic}\n\n{base}\n\n{link}'.strip()}


# ---------------- YouTube ----------------
def youtube_body(texts, publish_at, cfg):
    status = {'selfDeclaredMadeForKids': False}
    if publish_at:
        status['privacyStatus'] = 'private'        # forced: YouTube publishes scheduled videos from private
        status['publishAt'] = publish_at
    else:
        status['privacyStatus'] = cfg.get('yt_privacy') if cfg.get('yt_privacy') in ('private', 'unlisted', 'public') \
            else 'private'
    return {'snippet': {'title': texts['title'], 'description': texts['description'], 'categoryId': '20',
                        'tags': ['gamedev', 'indie game', 'Stark World Engine']}, 'status': status}


def youtube_upload(rec, texts, cfg, status_cb=print):
    if classroom_mode():
        raise NotApproved('YouTube upload is switched off in classroom mode')
    if not os.path.isfile(CLIENT_SECRETS):
        status_cb(CLIENT_SECRETS_HELP)
        return {'youtube': 'skipped: client_secrets.json missing (see instructions)'}
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    try:
        creds = Credentials.from_authorized_user_file(YT_TOKEN, SCOPES) if os.path.isfile(YT_TOKEN) else None
    except (OSError, ValueError):              # damaged / half-written token file: sign in again
        creds = None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:  # noqa: BLE001 - e.g. invalid_grant: a "Testing" app's 7-day token ran out
            status_cb(f'YouTube sign-in expired ({str(e)[:80]}); opening the Google sign-in page again')
            creds = None
    if not creds or not creds.valid:
        creds = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES).run_local_server(port=0)
    with open(YT_TOKEN, 'w', encoding='utf-8') as f:
        f.write(creds.to_json())
    restrict_to_user(YT_TOKEN)                 # the refresh token is a channel credential: owner-only file
    yt = build('youtube', 'v3', credentials=creds, cache_discovery=False)
    media = MediaFileUpload(rec['final'], mimetype='video/mp4', chunksize=CHUNK, resumable=True)
    req = yt.videos().insert(part='snippet,status', body=youtube_body(texts, rec.get('publish_at'), cfg),
                             media_body=media)
    resp, tries = None, 0
    while resp is None:
        try:
            st, resp = req.next_chunk()
            if st:
                status_cb(f'YouTube upload {st.progress() * 100:.0f}%')
            tries = 0
        except HttpError as e:
            if e.resp.status not in (500, 502, 503, 504) or tries >= 8:
                raise
            tries += 1
            time.sleep(min(64, 2 ** tries) + random.random())
        except (OSError, ConnectionError):
            if tries >= 8:
                raise
            tries += 1
            time.sleep(min(64, 2 ** tries) + random.random())
    vid = resp['id']
    status_cb(f'YouTube upload done: https://youtu.be/{vid} ({youtube_body(texts, rec.get("publish_at"), cfg)["status"]})')
    return {'youtube': f'uploaded https://youtu.be/{vid}'}


# ---------------- drafts ----------------
def compose_urls(texts, cfg):
    sub = (cfg.get('substack_url') or '').rstrip('/')
    return {'x': 'https://x.com/intent/post?text=' + urllib.parse.quote(texts['x']),
            'instagram': 'https://www.instagram.com/',
            'substack': (sub + '/publish/post') if sub.startswith('https://') else 'https://substack.com/'}


def find_chrome():
    for c in CHROME:
        if os.path.isfile(c):
            return c
    return shutil.which('chrome') or shutil.which('google-chrome')


def open_in_chrome(url):
    c = find_chrome()
    if c:
        subprocess.Popen([c, url])
    else:
        import webbrowser
        webbrowser.open(url)


def write_drafts(rec, texts, cfg, platforms, open_browser=True, drafts=DRAFTS):
    out_dir = os.path.join(drafts, rec['session'])
    os.makedirs(out_dir, exist_ok=True)
    urls = compose_urls(texts, cfg)
    media = {'x': rec['social_clips'][:1] or [rec['final']], 'instagram': rec['social_clips'] or [rec['final']],
             'substack': [rec['final']]}
    done = {}
    for p in platforms:
        if p not in urls:
            continue
        path = os.path.join(out_dir, f'{p}_draft.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f'{p.upper()} DRAFT - nothing has been posted. Paste/attach it yourself on the page that opened.\n\n'
                    f'--- text ---\n{texts[p]}\n\n--- media to attach ---\n' + '\n'.join(media[p]) + '\n'
                    + (f'\n--- scheduled time ---\n{rec["publish_at"]}\n' if rec.get('publish_at') else '')
                    + f'\n--- compose page ---\n{urls[p]}\n')
        if open_browser:
            open_in_chrome(urls[p])
        done[p] = path
    return done


def setup_wizard(open_browser=True):
    rows = ''.join(f'<li><label><input type="checkbox"> {t}</label> - <a href="{u}" target="_blank" rel="noopener">{u}</a></li>'
                   for t, u in WIZARD)
    page = ('<!doctype html><meta charset="utf-8"><title>Stark World Engine setup checklist</title><body style="font:16px system-ui;'
            'max-width:760px;margin:24px auto;padding:0 16px"><h1>Setup checklist</h1><p>Every page below is the '
            'official site. You sign up, accept terms and click everything yourself; Stark World Engine never logs in or '
            'creates accounts for you.</p><ol>' + rows + '</ol><p>Save the Google OAuth JSON as client_secrets.json in '
            'the Stark World Engine folder. Put an itch.io API key in config.json "itch_api_key" if you want the stats '
            'card. Optional local AI captions: install Ollama and set "ollama_model".</p></body>')
    os.makedirs(STATE, exist_ok=True)
    p = os.path.join(STATE, 'setup_checklist.html')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(page)
    if open_browser:
        open_in_chrome(p)
        for _, u in WIZARD:
            open_in_chrome(u)
    return p


def write_status(rec, result, approvals=APPROVALS):
    p = os.path.join(approvals, rec['session'] + '.status.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'at': datetime.datetime.now().isoformat(timespec='seconds'), **result}, f, indent=2)
    return p


def main(argv=None):
    if classroom_mode():
        print('REFUSED: publishing is switched off in classroom mode (config.json classroom_profile).')
        return 3
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--approval')
    ap.add_argument('--setup-wizard', action='store_true')
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--dry-run', action='store_true', help='check the approval and write drafts, upload nothing')
    a = ap.parse_args(argv)
    if a.setup_wizard:
        print('checklist:', setup_wizard(not a.no_browser))
        return 0
    cfg = load_config()
    try:
        rec = verify_approval(a.approval, cfg)
    except NotApproved as e:
        log.warning('refused: %s', e)
        print('REFUSED:', e)
        return 3
    log.info('approved session %s platforms=%s publish_at=%s', rec['session'], rec['platforms'], rec.get('publish_at'))
    texts = post_texts(rec, cfg)
    result = {'session': rec['session']}
    say = lambda m: (print(m), log.info(m))
    if 'youtube' in rec['platforms']:
        if a.dry_run:
            result['youtube'] = 'dry run: not uploaded'
            say('YouTube (dry run) body: ' + json.dumps(youtube_body(texts, rec.get('publish_at'), cfg)))
        else:
            try:
                result.update(youtube_upload(rec, texts, cfg, say))
            except Exception as e:  # noqa: BLE001
                result['youtube'] = f'failed: {e}'
                log.error('youtube: %s', e)
    drafts = write_drafts(rec, texts, cfg, [p for p in rec['platforms'] if p != 'youtube'], not a.no_browser)
    result['drafts'] = drafts
    say(f'drafts written: {", ".join(drafts) or "none"} (nothing posted; compose pages opened for you to finish)')
    write_status(rec, result)
    return 0


if __name__ == '__main__':
    sys.exit(main())
