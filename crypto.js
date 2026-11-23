/**
 * Decrypt data.enc.json with WebCrypto.
 *
 * The file is JSON: version 1, kdf "PBKDF2-SHA256", iterations, salt, iv,
 * ciphertext. Salt is 16 bytes, iv is 12 bytes, ciphertext is AES-GCM with a
 * 128-bit tag appended. The key is 256 bits from PBKDF2-HMAC-SHA256 over the
 * UTF-8 passcode. No associated data is used.
 *
 * tools/crypto_box.py produces this same layout.
 */

export const MIN_ITERATIONS = 250000;
export const MAX_ITERATIONS = 1000000;

export async function decryptPayload(file, passcode) {
  if (!globalThis.crypto || !crypto.subtle) {
    throw new Error("This browser cannot unlock the dashboard because WebCrypto is unavailable.");
  }
  if (!file || file.version !== 1) {
    throw new Error("Unsupported encrypted file version.");
  }
  if (file.kdf !== "PBKDF2-SHA256") {
    throw new Error("Unsupported key derivation.");
  }
  if (!Number.isInteger(file.iterations)) {
    throw new Error("Iteration count is missing.");
  }
  if (file.iterations < MIN_ITERATIONS) {
    throw new Error("Key derivation iterations are too low.");
  }
  if (file.iterations > MAX_ITERATIONS) {
    throw new Error("Key derivation iterations are too high.");
  }
  if (typeof passcode !== "string" || passcode === "") {
    throw new Error("Passcode is empty.");
  }

  const salt = b64ToBytes(file.salt);
  const iv = b64ToBytes(file.iv);
  const ciphertext = b64ToBytes(file.ciphertext);
  if (salt.length !== 16) {
    throw new Error("Salt length is not 16 bytes.");
  }
  if (iv.length !== 12) {
    throw new Error("IV length is not 12 bytes.");
  }
  if (ciphertext.length < 16) {
    throw new Error("Ciphertext is too short.");
  }

  const key = await deriveKey(passcode, salt, file.iterations);
  let plain;
  try {
    plain = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv, tagLength: 128 },
      key,
      ciphertext
    );
  } catch (error) {
    throw new Error("That passcode did not decrypt the data.");
  }
  const text = new TextDecoder().decode(plain);
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error("Decrypted data was not JSON.");
  }
}

async function deriveKey(passcode, salt, iterations) {
  const material = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(passcode),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt,
      iterations,
      hash: "SHA-256",
    },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"]
  );
}

export function b64ToBytes(value) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error("Encrypted file is missing a base64 field.");
  }
  let binary;
  try {
    binary = atob(value);
  } catch (error) {
    throw new Error("Encrypted file fields are not valid base64.");
  }
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}
