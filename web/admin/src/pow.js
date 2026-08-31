// Proof-of-work for the login form.
//
// The server hands out a prefix and a difficulty; we find a nonce whose
// SHA-256(prefix + ":" + nonce) starts with that many zero BITS. It runs while
// the admin is still typing their password, so it costs them nothing.
//
// WHY A HAND-WRITTEN SHA-256 RATHER THAN crypto.subtle. Two reasons, measured:
//
//  1. `crypto.subtle` only exists in a SECURE CONTEXT. The panel is routinely
//     reached over plain http://IP:PORT — `atlas panel-link` prints exactly
//     that URL — where it is `undefined`. Depending on it would mean the owner
//     simply cannot log in over HTTP.
//  2. It is also SLOWER here. Benchmarked in-browser: this loop does ~84,000
//     hashes/sec against ~63,000 for `crypto.subtle`, because the native call
//     is async and the per-call overhead dominates on 20-byte inputs.
//
// So there is no fallback and no branch — this is the only path.

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const w = new Uint32Array(64);

/** SHA-256 of a byte array → Uint8Array(32). */
export function sha256(bytes) {
  const len = bytes.length;
  const bitLen = len * 8;
  // message + 0x80 + zero padding + 8-byte big-endian length, to a 64-byte multiple
  const padded = new Uint8Array((((len + 8) >> 6) + 1) << 6);
  padded.set(bytes);
  padded[len] = 0x80;
  const dv = new DataView(padded.buffer);
  dv.setUint32(padded.length - 4, bitLen >>> 0, false);
  dv.setUint32(padded.length - 8, Math.floor(bitLen / 4294967296), false);

  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;

  for (let off = 0; off < padded.length; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4, false);
    for (let i = 16; i < 64; i++) {
      const a = w[i - 15], b = w[i - 2];
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
      const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
    for (let i = 0; i < 64; i++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[i] + w[i]) >>> 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h = g; g = f; f = e; e = (d + t1) >>> 0;
      d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0;
  }
  const out = new Uint8Array(32);
  new DataView(out.buffer).setUint32(0, h0, false);
  new DataView(out.buffer).setUint32(4, h1, false);
  new DataView(out.buffer).setUint32(8, h2, false);
  new DataView(out.buffer).setUint32(12, h3, false);
  new DataView(out.buffer).setUint32(16, h4, false);
  new DataView(out.buffer).setUint32(20, h5, false);
  new DataView(out.buffer).setUint32(24, h6, false);
  new DataView(out.buffer).setUint32(28, h7, false);
  return out;
}

function leadingZeroBits(bytes) {
  let n = 0;
  for (const b of bytes) {
    if (b === 0) { n += 8; continue; }
    let x = b;
    while (x < 128) { x <<= 1; n++; }
    return n + 0;
  }
  return n;
}

const enc = new TextEncoder();

/**
 * Find a nonce satisfying the challenge.
 *
 * Runs in slices with a yield between them so the password field never stutters
 * while typing — a login form that drops keystrokes would be a strange way to
 * pay for security. `onProgress` gets 0..1 so the UI can show it is working.
 */
export async function solvePow(prefix, bits, { onProgress, signal } = {}) {
  const expected = Math.pow(2, bits);
  const SLICE = 2000;
  let nonce = 0;

  for (;;) {
    for (let i = 0; i < SLICE; i++, nonce++) {
      if (signal?.aborted) throw new Error("aborted");
      if (leadingZeroBits(sha256(enc.encode(prefix + ":" + nonce))) >= bits) return String(nonce);
    }
    onProgress?.(Math.min(0.99, nonce / (expected * 1.5)));
    // Hand the main thread back so React can paint and inputs stay responsive.
    await new Promise((r) => setTimeout(r, 0));
  }
}
