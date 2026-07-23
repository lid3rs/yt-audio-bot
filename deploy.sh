#!/usr/bin/env bash
# One-command deploy: build the image, push it to your registry, then
# create/update the Portainer stack with a forced image pull.
# All configuration lives in .env (see .env.example); no versioning — always one tag.
set -euo pipefail
cd "$(dirname "$0")"

set -a
source .env
set +a

: "${IMAGE:?Set IMAGE in .env (e.g. registry.example.com/yt-audio-bot:latest)}"
: "${PORTAINER_URL:?Set PORTAINER_URL in .env}"
: "${PORTAINER_API_KEY:?Set PORTAINER_API_KEY in .env}"
: "${PORTAINER_ENDPOINT_ID:?Set PORTAINER_ENDPOINT_ID in .env}"
export STACK_NAME="${STACK_NAME:-yt-audio-bot}"

echo "Building $IMAGE ..."
docker build --platform="${BUILD_PLATFORM:-linux/x86_64}" -t "$IMAGE" .

echo "Pushing ..."
docker push "$IMAGE"

echo "Deploying stack '$STACK_NAME' via Portainer ..."
python3 - <<'PY'
import hashlib, json, os, socket, ssl, sys, urllib.error, urllib.parse, urllib.request

url = os.environ["PORTAINER_URL"].rstrip("/")
endpoint = int(os.environ["PORTAINER_ENDPOINT_ID"])
name = os.environ["STACK_NAME"]
pin = os.environ.get("PORTAINER_TLS_FINGERPRINT", "").lower()

parsed = urllib.parse.urlparse(url)
host, port = parsed.hostname, parsed.port or 443

if pin:
    # Certificate pinning for Portainers with self-signed/expired certs: verify
    # the exact server certificate instead of the (broken) CA chain.
    probe = ssl._create_unverified_context()
    with socket.create_connection((host, port), timeout=15) as s:
        with probe.wrap_socket(s, server_hostname=host) as w:
            fp = hashlib.sha256(w.getpeercert(binary_form=True)).hexdigest()
    if fp != pin:
        sys.exit(f"Portainer TLS certificate changed!\n  got:      {fp}\n  expected: {pin}\n"
                 "If you replaced/renewed the cert, update PORTAINER_TLS_FINGERPRINT in .env.")
    ctx = ssl._create_unverified_context()  # authenticity established by the pin above
else:
    ctx = ssl.create_default_context()

headers = {"X-API-Key": os.environ["PORTAINER_API_KEY"], "Content-Type": "application/json"}

def api(path, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url + path, data=body, headers=headers, method=method)
    return json.load(urllib.request.urlopen(req, context=ctx))

stack_file = open("stack.portainer.yml").read()
env = [
    {"name": "BOT_TOKEN", "value": os.environ["BOT_TOKEN"]},
    {"name": "ALLOWED_USER_ID", "value": os.environ["ALLOWED_USER_ID"]},
    {"name": "IMAGE", "value": os.environ["IMAGE"]},
]

existing = next((s for s in api("/api/stacks") if s["Name"] == name), None)
if existing:
    api(f"/api/stacks/{existing['Id']}?endpointId={endpoint}", "PUT", {
        "env": env,
        "stackFileContent": stack_file,
        "pullImage": True,
        "prune": True,
    })
    print("stack updated (image pulled)")
else:
    try:
        api(f"/api/stacks/create/standalone/string?endpointId={endpoint}", "POST", {
            "name": name, "stackFileContent": stack_file, "env": env, "fromAppTemplate": False,
        })
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # older Portainer API route
        api(f"/api/stacks?type=2&method=string&endpointId={endpoint}", "POST", {
            "name": name, "stackFileContent": stack_file, "env": env,
        })
    print("stack created")
PY

echo "Done. Message the bot in Telegram, or check the container logs."
