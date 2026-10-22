import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import type { FileHandle } from "node:fs/promises";
import { Uint8ArrayReader, Uint8ArrayWriter, ZipReader, type Entry } from "@zip.js/zip.js";

import {
  FULL_AOT_KIND,
  SPLIT_SNAPSHOT_SYMBOLS,
  UNIFIED_SNAPSHOT_SYMBOLS,
  readElfHeader,
  readElfSymbols,
  readSnapshotHeader,
  snapshotLayout,
} from "./DartElf.js";
import { readElfBuildIds } from "./ElfBuildId.js";
import { LabeledStringScanner, SnapshotHashScanner } from "./FlutterPayloadScan.js";
import { flutterResultSchemas } from "../domain/flutter/flutterBuildAnalysis.js";

/**
 * Flutter payloads inside an APK: lib/<abi>/libapp.so (the Dart AOT
 * snapshot) and lib/<abi>/libflutter.so (the engine). Members are read
 * from the archive in memory; nothing is loaded or executed.
 */
const PREFERRED_ABIS = ["arm64-v8a", "x86_64", "x86", "armeabi-v7a"];
const MEMBER = /^lib\/([^/]+)\/(libapp\.so|libflutter\.so)$/u;
/** Largest library member read into memory. */
const MAX_MEMBER_BYTES = 512 * 1024 * 1024;
const MAX_BUILD_ID_CANDIDATES = 64;
const MAX_POOL_ITEMS = 500;
const MAX_POOL_DISTINCT = 100_000;
const MIN_PRINTABLE_RUN = 4;

const sha256 = (bytes: Uint8Array): string => createHash("sha256").update(bytes).digest("hex");

const abiOrder = (abis: Iterable<string>): string[] =>
  [...new Set(abis)].sort((left, right) => {
    const a = PREFERRED_ABIS.indexOf(left);
    const b = PREFERRED_ABIS.indexOf(right);
    if (a !== -1 || b !== -1) return (a === -1 ? 99 : a) - (b === -1 ? 99 : b);
    return left < right ? -1 : left > right ? 1 : 0;
  });

/** A FileHandle-shaped reader over bytes already in memory. */
const memoryHandle = (bytes: Buffer): FileHandle =>
  ({
    read: async (buffer: Buffer, offset: number, length: number, position: number) => {
      const count = Math.max(0, Math.min(length, bytes.length - position));
      if (count > 0) bytes.copy(buffer, offset, position, position + count);
      return { bytesRead: count, buffer };
    },
  }) as unknown as FileHandle;

interface Libraries {
  readonly target: { path: string; bytes: number; sha256: string };
  readonly members: Map<string, { libapp?: Entry; libflutter?: Entry }>;
  read(entry: Entry): Promise<Buffer>;
  close(): Promise<void>;
}

const openApk = async (bytes: Buffer, path: string): Promise<Libraries> => {
  const reader = new ZipReader(new Uint8ArrayReader(bytes), { useWebWorkers: false });
  let entries: Entry[];
  try {
    entries = await reader.getEntries();
  } catch (error) {
    await reader.close().catch(() => undefined);
    throw new Error(`Not a readable APK (zip): ${(error as Error).message}`);
  }
  const members = new Map<string, { libapp?: Entry; libflutter?: Entry }>();
  for (const entry of entries) {
    if (entry.directory) continue;
    const match = MEMBER.exec(entry.filename);
    if (!match) continue;
    const slot = members.get(match[1]) ?? {};
    const key = match[2] === "libapp.so" ? "libapp" : "libflutter";
    if (slot[key] !== undefined) {
      await reader.close().catch(() => undefined);
      throw new Error(`APK names ${entry.filename} more than once`);
    }
    slot[key] = entry;
    members.set(match[1], slot);
  }
  return {
    target: { path, bytes: bytes.length, sha256: sha256(bytes) },
    members,
    async read(entry: Entry) {
      if (entry.uncompressedSize > MAX_MEMBER_BYTES)
        throw new Error(`${entry.filename} declares ${entry.uncompressedSize} bytes, above the ${MAX_MEMBER_BYTES}-byte member limit`);
      const data = await (entry as Entry & { getData(writer: Uint8ArrayWriter, options?: object): Promise<Uint8Array> })
        .getData(new Uint8ArrayWriter(), { useWebWorkers: false, checkSignature: true });
      return Buffer.from(data.buffer, data.byteOffset, data.byteLength);
    },
    close: () => reader.close(),
  };
};

/** identify_flutter_build: which ABIs carry Flutter payloads, their hashes and engine identity. */
export const identifyFlutterBuild = async (bytes: Buffer, path: string) => {
  const apk = await openApk(bytes, path);
  try {
    let partial = false;
    const abis = [];
    for (const abi of abiOrder(apk.members.keys())) {
      const slot = apk.members.get(abi)!;
      const libapp = {
        present: false, bytes: null as number | null, sha256: null as string | null,
        elf_header_valid: null as boolean | null, snapshot_hash_sources: 0,
        snapshot_hash_candidates: [] as string[], snapshot_hash: null as string | null,
      };
      if (slot.libapp) {
        const data = await apk.read(slot.libapp);
        const scanner = new SnapshotHashScanner();
        scanner.push(data);
        const scan = scanner.result();
        Object.assign(libapp, {
          present: true, bytes: data.length, sha256: sha256(data),
          elf_header_valid: readElfHeader(data).failure === undefined,
          snapshot_hash_sources: scan.sources, snapshot_hash_candidates: [...scan.candidates],
          snapshot_hash: scan.candidates.length === 1 && !scan.capped ? scan.candidates[0] : null,
        });
        if (!libapp.elf_header_valid || scan.capped || scan.candidates.length !== 1) partial = true;
      }
      const libflutter = {
        present: false, bytes: null as number | null, sha256: null as string | null,
        build_id: null as string | null, build_id_candidates: [] as string[],
        dart_version: null as string | null, toolchain_lines: [] as string[],
        dart_version_capped: false, toolchain_capped: false,
      };
      if (slot.libflutter) {
        const data = await apk.read(slot.libflutter);
        const build = await readElfBuildIds(memoryHandle(data), data.length, undefined);
        const labels = new LabeledStringScanner();
        labels.push(data);
        const found = labels.result();
        const candidates = [...build.candidates].slice(0, MAX_BUILD_ID_CANDIDATES);
        Object.assign(libflutter, {
          present: true, bytes: data.length, sha256: sha256(data),
          build_id: candidates.length === 1 && build.failures.length === 0 ? candidates[0] : null,
          build_id_candidates: candidates,
          dart_version: found.dartVersion, toolchain_lines: [...found.toolchainLines],
          dart_version_capped: found.dartVersionCapped, toolchain_capped: found.toolchainCapped,
        });
        if (build.failures.length > 0 || build.candidates.length !== 1 || found.dartVersionCapped || found.toolchainCapped)
          partial = true;
      }
      abis.push({ abi, libapp, libflutter });
    }
    return flutterResultSchemas.identify_flutter_build.parse({
      target: apk.target,
      flutter_detected: abis.length > 0,
      abis,
      coverage: partial ? "partial" : "complete",
    });
  } finally {
    await apk.close();
  }
};

/** Distinct values kept in order of discovery, bounded; the count keeps growing to a hard cap. */
class Bounded {
  readonly seen = new Set<string>();
  capped = false;
  add(value: string) {
    if (this.seen.has(value)) return;
    if (this.seen.size >= MAX_POOL_DISTINCT) this.capped = true;
    else this.seen.add(value);
  }
  list(): string[] {
    return [...this.seen].sort().slice(0, MAX_POOL_ITEMS);
  }
  clipped(): boolean {
    return this.capped || this.seen.size > MAX_POOL_ITEMS;
  }
}

const PACKAGE_URI = /package:[A-Za-z0-9_.-]+\/[A-Za-z0-9_./-]*\.dart/gu;
const DART_URI = /dart:_?[a-z][a-z0-9_]*/gu;
// Two or more capitalized humps: class names such as GaugeWidget or StatefulElement.
const CLASS_LIKE = /(?<![A-Za-z0-9_])_?[A-Z][a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+(?![A-Za-z0-9_])/gu;

const stringPool = (data: Buffer) => {
  const packages = new Bounded();
  const darts = new Bounded();
  const classes = new Bounded();
  let runs = 0;
  let start = -1;
  const consider = (end: number) => {
    if (start < 0 || end - start < MIN_PRINTABLE_RUN) return;
    runs += 1;
    const text = data.subarray(start, end).toString("latin1");
    for (const match of text.matchAll(PACKAGE_URI)) packages.add(match[0]);
    for (const match of text.matchAll(DART_URI)) darts.add(match[0]);
    for (const match of text.matchAll(CLASS_LIKE)) classes.add(match[0]);
  };
  for (let index = 0; index < data.length; index += 1) {
    const byte = data[index];
    if (byte >= 0x20 && byte < 0x7f) {
      if (start < 0) start = index;
    } else {
      consider(index);
      start = -1;
    }
  }
  consider(data.length);
  const clipped = packages.clipped() || darts.clipped() || classes.clipped();
  return {
    coverage: clipped ? ("partial" as const) : ("complete" as const),
    package_uris: packages.list(),
    package_uri_count_at_least: packages.seen.size,
    dart_uris: darts.list(),
    dart_uri_count_at_least: darts.seen.size,
    class_like_tokens: classes.list(),
    class_like_token_count_at_least: classes.seen.size,
    printable_run_count: runs,
  };
};

/** inspect_dart_aot: the exported snapshot sections of one ABI's libapp.so and its string pool. */
export const inspectDartAot = async (bytes: Buffer, path: string, parameters: { abi?: string | undefined }) => {
  if (parameters.abi !== undefined && !/^[a-z0-9_-]{2,16}$/u.test(parameters.abi))
    throw new Error("abi must be 2 to 16 characters of a-z, 0-9, _ or -");
  const apk = await openApk(bytes, path);
  try {
    const available = abiOrder([...apk.members].filter(([, slot]) => slot.libapp).map(([abi]) => abi));
    const abi = parameters.abi ?? available[0];
    if (abi === undefined) throw new Error("The APK carries no lib/<abi>/libapp.so");
    if (!available.includes(abi))
      throw new Error(`The APK has no lib/${abi}/libapp.so; ABIs with libapp.so: ${available.join(", ") || "none"}`);
    const data = await apk.read(apk.members.get(abi)!.libapp!);
    const header = readElfHeader(data);
    const symbols = header.failure === undefined
      ? await readElfSymbols(data, [...SPLIT_SNAPSHOT_SYMBOLS, ...UNIFIED_SNAPSHOT_SYMBOLS])
      : { symbols: [], failures: [header.failure] };
    const found = symbols.symbols.map((row) => row.name);
    const layout = snapshotLayout(found);
    const aotKind = layout === null ? null : FULL_AOT_KIND[layout];
    const order = [...SPLIT_SNAPSHOT_SYMBOLS, ...UNIFIED_SNAPSHOT_SYMBOLS] as readonly string[];
    const sections = [...symbols.symbols]
      .sort((left, right) => order.indexOf(left.name) - order.indexOf(right.name))
      .map((row) => {
        const isData = row.name.endsWith("SnapshotData");
        const read = isData ? readSnapshotHeader(data, row.offset, aotKind) : null;
        return {
          row,
          read,
          section: {
            name: row.name, offset: row.offset, size: row.size,
            magic_valid: read?.magicValid ?? false,
            kind: read?.kind ?? null,
            header_length: read?.headerLength ?? null,
          },
        };
      });
    const data_sections = sections.filter((item) => item.read !== null);
    const hashes = data_sections.map((item) => item.read!.hash).filter((hash): hash is string => hash !== null);
    const candidates = [...new Set(hashes)];
    const expected = layout === "unified" ? ["_kDartSnapshotData"] : ["_kDartVmSnapshotData", "_kDartIsolateSnapshotData"];
    const extentsFit = sections.every((item) => item.row.offset + item.row.size <= data.length);
    const complete =
      header.failure === undefined &&
      layout !== null &&
      expected.every((name) => data_sections.some((item) => item.row.name === name && item.read!.complete)) &&
      candidates.length === 1 &&
      extentsFit;
    const pool = stringPool(data);
    return flutterResultSchemas.inspect_dart_aot.parse({
      target: apk.target,
      abi,
      libapp: {
        coverage: complete ? "complete" : "partial",
        bytes: data.length,
        sha256: sha256(data),
        snapshot_hash: candidates.length === 1 ? candidates[0] : null,
        snapshot_hash_candidates: candidates,
        snapshot_hash_sources: hashes.length,
        sections: sections.map((item) => item.section),
      },
      string_pool: pool,
      coverage: complete && pool.coverage === "complete" ? "complete" : "partial",
    });
  } finally {
    await apk.close();
  }
};
