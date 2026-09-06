"""Shadowsocks-2022 keys — the two properties that silently take an inbound down.

Plain `python tests/test_ss2022.py`.

What is being protected: SS2022 takes a pre-shared KEY of an exact length, not a
password, and xray refuses to load an inbound where ANY user's key is the wrong
size. One malformed client therefore kills every other client sharing that
inbound — the failure is not local to the customer who caused it.

  * **Size.** Every generated key must decode to exactly the cipher's key length.
  * **Stability.** The same client uuid must always produce the same key.
    add_client is retried on failure and update_client refuses to write when a
    client's identity would change, so a key drawn at random on the second
    attempt would lock the customer out of the config they already installed.
"""
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("BOT_TOKEN", "")

from core.xui_api import SS2022_KEY_BYTES, XUIClient, _ss_secret, is_ss2022  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILED = []


def check(label, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + label + f"   got={got!r} want={want!r}")
    if not ok:
        FAILED.append(label)


UUID = "7f3a1c9e-2b44-4d1a-9c8e-0a1b2c3d4e5f"
OTHER = "11111111-2222-3333-4444-555555555555"

print("\nkey size, per cipher")
for method, size in SS2022_KEY_BYTES.items():
    key = _ss_secret(method, UUID)
    check(f"{method} decodes to {size}B", len(base64.b64decode(key)), size)

print("\nstability")
check("same uuid, same key", _ss_secret("2022-blake3-aes-128-gcm", UUID),
      _ss_secret("2022-blake3-aes-128-gcm", UUID))
check("different uuid, different key",
      _ss_secret("2022-blake3-aes-128-gcm", UUID) != _ss_secret("2022-blake3-aes-128-gcm", OTHER), True)
check("cipher change gives a new key",
      _ss_secret("2022-blake3-aes-128-gcm", UUID) != _ss_secret("2022-blake3-aes-256-gcm", UUID), True)

print("\nan existing key is respected, a bad one is replaced")
good = base64.b64encode(b"0123456789abcdef").decode()
check("valid key kept", _ss_secret("2022-blake3-aes-128-gcm", UUID, good), good)
check("wrong-size key replaced",
      len(base64.b64decode(_ss_secret("2022-blake3-aes-128-gcm", UUID,
                                      base64.b64encode(b"0" * 32).decode()))), 16)
check("non-base64 key replaced",
      len(base64.b64decode(_ss_secret("2022-blake3-aes-128-gcm", UUID, "hunter2!!"))), 16)

print("\nlegacy AEAD ciphers are left alone")
check("aes-256-gcm takes any string", _ss_secret("aes-256-gcm", UUID), UUID.replace("-", ""))
check("its existing password is kept", _ss_secret("aes-256-gcm", UUID, "whatever"), "whatever")
check("is_ss2022 says no", is_ss2022("aes-256-gcm"), False)
check("is_ss2022 says yes", is_ss2022("2022-blake3-aes-128-gcm"), True)

print("\nthe client payload uses it")
cli = XUIClient("https://example.invalid", "u", "p")
pay = cli._client_payload("shadowsocks", UUID, "a@b", 1, 0, True,
                          method="2022-blake3-aes-128-gcm")
check("payload key is 16B", len(base64.b64decode(pay["password"])), 16)
check("no per-client method on an SS2022 inbound",
      "method" in cli._client_payload("shadowsocks", UUID, "a@b", 1, 0, True,
                                      {"method": "aes-256-gcm"}, "2022-blake3-aes-128-gcm"), False)
check("but kept on a legacy inbound",
      cli._client_payload("shadowsocks", UUID, "a@b", 1, 0, True,
                          {"method": "aes-256-gcm"}, "aes-256-gcm").get("method"), "aes-256-gcm")
check("inbound method read from a JSON string",
      cli._inbound_method({"settings": '{"method":"2022-blake3-aes-256-gcm"}'}),
      "2022-blake3-aes-256-gcm")
check("...and from a dict", cli._inbound_method({"settings": {"method": "aes-128-gcm"}}), "aes-128-gcm")
check("...and survives junk", cli._inbound_method({"settings": "not json"}), "")

print("\n" + ("ALL PASSED" if not FAILED else f"FAILED: {FAILED}"))
sys.exit(1 if FAILED else 0)
