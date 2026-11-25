// SB3 UTAGE:INDO patcher core: reads a launcher .patch (SB3UPAT1, tools/u_make_patch.py) and rebuilds
// each translated file from the player's own game, as the Android app does (GamePatch.java, Vcdiff.java).
// Shared by the web patcher (docs/patcher/index.html) and its Node test (tools/u_web_patcher_test.mjs).

const NOOP = 0, ADD = 1, RUN = 2, COPY = 3;
const S_NEAR = 4, S_SAME = 3;

// RFC 3284 5.6, the default code table: [type1, size1, mode1, type2, size2, mode2].
const TABLE = (() => {
  const t = [];
  t.push([RUN, 0, 0, NOOP, 0, 0]);
  t.push([ADD, 0, 0, NOOP, 0, 0]);
  for (let s = 1; s <= 17; s++) t.push([ADD, s, 0, NOOP, 0, 0]);
  for (let m = 0; m < 9; m++) {
    t.push([COPY, 0, m, NOOP, 0, 0]);
    for (let s = 4; s <= 18; s++) t.push([COPY, s, m, NOOP, 0, 0]);
  }
  for (let m = 0; m < 6; m++)
    for (let a = 1; a <= 4; a++)
      for (let c = 4; c <= 6; c++) t.push([ADD, a, 0, COPY, c, m]);
  for (let m = 6; m < 9; m++)
    for (let a = 1; a <= 4; a++) t.push([ADD, a, 0, COPY, 4, m]);
  for (let m = 0; m < 9; m++) t.push([COPY, 4, m, ADD, 1, 0]);
  if (t.length !== 256) throw new Error('code table ' + t.length);
  return t;
})();

class PatchError extends Error {}
const damaged = (what) => new PatchError('patch rusak (' + what + ')');

function adler32(b, start, len) {
  let a = 1, s = 0;
  for (let i = start, end = start + len; i < end;) {
    const chunkEnd = Math.min(end, i + 3800);
    for (; i < chunkEnd; i++) { a += b[i]; s += a; }
    a %= 65521; s %= 65521;
  }
  return ((s << 16) | a) >>> 0;
}

/** VCDIFF as xdelta3 3.1 writes it with -S none -A: `patch` applied to `source`, `size` bytes out. */
export function vcdiffDecode(source, patch, size) {
  let p = 0;
  const u8 = () => { if (p >= patch.length) throw damaged('terpotong'); return patch[p++]; };
  const varint = () => { let v = 0, c; do { c = u8(); v = v * 128 + (c & 0x7f); } while (c & 0x80); return v; };
  if (u8() !== 0xd6 || u8() !== 0xc3 || u8() !== 0xc4 || u8() !== 0) throw damaged('header');
  const hdr = u8();
  if (hdr & 1) throw damaged('secondary compression');
  if (hdr & 2) throw damaged('code table');
  if (hdr & 4) p += varint();
  const out = new Uint8Array(size);
  const near = new Int32Array(S_NEAR), same = new Int32Array(S_SAME * 256);
  let written = 0;
  while (p < patch.length) {
    const wi = u8();
    if (wi & 2) throw damaged('VCD_TARGET');
    let srcLen = 0, srcPos = 0;
    if (wi & 1) {
      srcLen = varint();
      srcPos = varint();
      if (srcPos + srcLen > source.length) throw damaged('source window');
    }
    varint();
    const tgtLen = varint();
    if (u8() !== 0) throw damaged('compressed sections');
    const dataLen = varint(), instLen = varint(), addrLen = varint();
    let sum = -1;
    if (wi & 4) sum = ((u8() << 24) >>> 0) + (u8() << 16) + (u8() << 8) + u8();
    let dp = p, ip = dp + dataLen, ap = ip + instLen;
    const instEnd = ap, end = ap + addrLen;
    if (end > patch.length || written + tgtLen > size) throw damaged('window size');
    near.fill(0);
    same.fill(0);
    const base = written;
    let nextSlot = 0, t = 0;
    while (ip < instEnd) {
      const e = TABLE[patch[ip++]];
      for (let half = 0; half < 2; half++) {
        const type = e[half * 3], mode = e[half * 3 + 2];
        let n = e[half * 3 + 1];
        if (type === NOOP) continue;
        if (n === 0) { let v = 0, c; do { c = patch[ip++]; v = v * 128 + (c & 0x7f); } while (c & 0x80); n = v; }
        if (t + n > tgtLen) throw damaged('instruction size');
        if (type === ADD) {
          out.set(patch.subarray(dp, dp + n), base + t);
          dp += n; t += n;
        } else if (type === RUN) {
          out.fill(patch[dp++], base + t, base + t + n);
          t += n;
        } else {
          const here = srcLen + t;
          let a;
          if (mode < 2 + S_NEAR) {
            let v = 0, c; do { c = patch[ap++]; v = v * 128 + (c & 0x7f); } while (c & 0x80);
            a = mode === 0 ? v : mode === 1 ? here - v : near[mode - 2] + v;
          } else {
            a = same[(mode - 2 - S_NEAR) * 256 + patch[ap++]];
          }
          near[nextSlot] = a;
          nextSlot = (nextSlot + 1) % S_NEAR;
          same[a % (S_SAME * 256)] = a;
          if (a < 0 || a >= here) throw damaged('copy address');
          if (a < srcLen) {
            const k = Math.min(n, srcLen - a);
            out.set(source.subarray(srcPos + a, srcPos + a + k), base + t);
            t += k; n -= k; a = srcLen;
          }
          const from = base + a - srcLen;
          for (let k = 0; k < n; k++) out[base + t + k] = out[from + k];
          t += n;
        }
      }
    }
    if (t !== tgtLen || dp !== instEnd - instLen || ap !== end) throw damaged('window end');
    if (sum >= 0 && adler32(out, base, tgtLen) !== sum) throw damaged('window checksum');
    written += tgtLen;
    p = end;
  }
  if (written !== size) throw damaged('size');
  return out;
}

async function sha1(bytes) {
  return new Uint8Array(await crypto.subtle.digest('SHA-1', bytes));
}

function sameBytes(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

async function inflate(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Sequential reads from a Blob/File in large slices. */
class BlobReader {
  constructor(blob) { this.blob = blob; this.pos = 0; this.buf = new Uint8Array(0); this.bufPos = 0; }
  async fill(n) {
    if (this.buf.length - this.bufPos >= n) return;
    const keep = this.buf.subarray(this.bufPos);
    const want = Math.max(n - keep.length, 8 << 20);
    const chunk = new Uint8Array(await this.blob.slice(this.pos, this.pos + want).arrayBuffer());
    this.pos += chunk.length;
    const merged = new Uint8Array(keep.length + chunk.length);
    merged.set(keep); merged.set(chunk, keep.length);
    this.buf = merged; this.bufPos = 0;
    if (this.buf.length < n) throw damaged('file terpotong');
  }
  async bytes(n) { await this.fill(n); const b = this.buf.slice(this.bufPos, this.bufPos + n); this.bufPos += n; return b; }
  async u8() { return (await this.bytes(1))[0]; }
  async u16() { const b = await this.bytes(2); return (b[0] << 8) | b[1]; }
  async u32() { const b = await this.bytes(4); return ((b[0] << 24) >>> 0) + (b[1] << 16) + (b[2] << 8) + b[3]; }
  async text(n) { return new TextDecoder().decode(await this.bytes(n)); }
}

/** The patch's header: {id, name, version, description, files, bytes, xml_name, xml, game}. */
export async function readHeader(blob) {
  const r = new BlobReader(blob);
  if (await r.text(8) !== 'SB3UPAT1') throw new PatchError('Ini bukan file patch SB3 UTAGE:INDO (.patch).');
  const header = JSON.parse(await r.text(await r.u32()));
  return { header, reader: r };
}

/**
 * Rebuilds every file of `blob` (a .patch): `readOriginal(discPath)` gives the original game file
 * ("files/nativeWii/...") as a Uint8Array or null, `writeOutput(path, bytes)` takes each result
 * ("S3HJ08/nativeWii/..." and "riivolution/<xml>"). `onProgress({done, total, bytes, path})`.
 * Throws PatchError with the first file that does not match.
 */
export async function applyPatch(blob, { readOriginal, writeOutput, onProgress, signal }) {
  const { header, reader: r } = await readHeader(blob);
  if (header.game !== 'S3HJ08') throw new PatchError('Patch ini untuk game ' + header.game + ', bukan S3HJ08.');
  let bytes = 0;
  for (let i = 0; i < header.files; i++) {
    if (signal && signal.aborted) throw new PatchError('Dibatalkan.');
    const out = await r.text(await r.u16());
    const disc = await r.text(await r.u16());
    const kind = await r.u8();
    const srcSize = await r.u32();
    const srcSha = await r.bytes(20);
    const dstSize = await r.u32();
    const dstSha = await r.bytes(20);
    const payload = await inflate(await r.bytes(await r.u32()));
    let result;
    if (kind === 0) {
      const src = await readOriginal(disc);
      if (!src) throw new PatchError('File game tidak ditemukan: ' + disc + '. Pastikan folder yang dipilih adalah hasil Extract Entire Disc dari Sengoku Basara 3 Utage (S3HJ08).');
      if (src.length !== srcSize || !sameBytes(await sha1(src), srcSha)) {
        throw new PatchError('File game berbeda dari disc asli: ' + disc + '. Patch butuh dump asli S3HJ08 yang belum dimodifikasi.');
      }
      result = vcdiffDecode(src, payload, dstSize);
    } else {
      result = payload;
    }
    if (result.length !== dstSize || !sameBytes(await sha1(result), dstSha)) throw new PatchError('Hasil tidak cocok: ' + out);
    await writeOutput(out, result);
    bytes += result.length;
    if (onProgress) onProgress({ done: i + 1, total: header.files, bytes, path: out });
  }
  if (await r.text(8) !== 'SB3UEND1' || await r.u32() !== header.files) throw damaged('trailer');
  await writeOutput('riivolution/' + header.xml_name, new TextEncoder().encode(header.xml));
  return header;
}

export { PatchError };
