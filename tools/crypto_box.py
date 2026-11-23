"""AES-GCM encryption compatible with crypto.js in the browser.

File format (JSON):
  version: 1
  kdf: "PBKDF2-SHA256"
  iterations: integer >= 250000
  salt: standard base64, 16 bytes
  iv: standard base64, 12 bytes
  ciphertext: standard base64 of AES-GCM ciphertext with the 16-byte tag appended

The key is 32 bytes from PBKDF2-HMAC-SHA256 over the UTF-8 passcode.
No associated data is used.
"""

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MIN_ITERATIONS = 250_000
MAX_ITERATIONS = 1_000_000
SALT_BYTES = 16
IV_BYTES = 12
KEY_BYTES = 32
VERSION = 1
KDF = "PBKDF2-SHA256"


class CryptoError(ValueError):
    """The encrypted file could not be read or written."""


def encrypt_payload(payload, passcode, iterations=MIN_ITERATIONS):
    """Encrypt a JSON-serialisable object. Returns the file document."""
    if not isinstance(passcode, str) or passcode == "":
        raise CryptoError("Passcode is empty.")
    if not isinstance(iterations, int) or not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        raise CryptoError("Iteration count is outside the supported range.")
    salt = os.urandom(SALT_BYTES)
    iv = os.urandom(IV_BYTES)
    key = _derive_key(passcode, salt, iterations)
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    return {
        "version": VERSION,
        "kdf": KDF,
        "iterations": iterations,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_payload(document, passcode):
    """Decrypt a document produced by encrypt_payload or by the same steps."""
    salt, iv, ciphertext, iterations = _validated_parts(document)
    if not isinstance(passcode, str) or passcode == "":
        raise CryptoError("Passcode is empty.")
    key = _derive_key(passcode, salt, iterations)
    try:
        plaintext = AESGCM(key).decrypt(iv, ciphertext, None)
    except Exception as exc:
        raise CryptoError("Decryption failed.") from exc
    try:
        return json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CryptoError("Decrypted data was not JSON.") from exc


def _validated_parts(document):
    if not isinstance(document, dict):
        raise CryptoError("Encrypted file must be a JSON object.")
    if document.get("version") != VERSION:
        raise CryptoError("Unsupported encrypted file version.")
    if document.get("kdf") != KDF:
        raise CryptoError("Unsupported key derivation.")
    iterations = document.get("iterations")
    if not isinstance(iterations, int) or isinstance(iterations, bool):
        raise CryptoError("Iteration count is missing.")
    if iterations < MIN_ITERATIONS:
        raise CryptoError("Key derivation iterations are too low.")
    if iterations > MAX_ITERATIONS:
        raise CryptoError("Key derivation iterations are too high.")
    try:
        salt = base64.b64decode(document["salt"], validate=True)
        iv = base64.b64decode(document["iv"], validate=True)
        ciphertext = base64.b64decode(document["ciphertext"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise CryptoError("Encrypted file fields are not valid base64.") from exc
    if len(salt) != SALT_BYTES:
        raise CryptoError("Salt length is not 16 bytes.")
    if len(iv) != IV_BYTES:
        raise CryptoError("IV length is not 12 bytes.")
    if len(ciphertext) < 16:
        raise CryptoError("Ciphertext is too short.")
    return salt, iv, ciphertext, iterations


def _derive_key(passcode, salt, iterations):
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(passcode.encode("utf-8"))
