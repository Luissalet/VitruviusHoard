import {
  classifyFatContainerIdentity,
  readFatContainerHeader,
  validateFatSliceIdentity,
  type FatSliceDeclaration,
} from "../domain/apple/machoContainer.js";

const MACHO_BIG = [0xfeedface, 0xfeedfacf];
const MACHO_LITTLE = [0xcefaedfe, 0xcffaedfe];

/** One declared architecture of a universal file, with its exact thin bytes. */
export interface UniversalMachoSlice {
  readonly index: number;
  readonly file_offset: number;
  readonly file_bytes: number;
  readonly cpu_type: number;
  readonly cpu_subtype: number;
  readonly bytes: Buffer;
  /** Null when the slice header repeats the table's CPU type and subtype. */
  readonly identity_failure: string | null;
}

/** Architecture table of a confirmed universal Mach-O. */
export interface UniversalMacho {
  readonly magic: number;
  readonly wide: boolean;
  readonly slices: readonly UniversalMachoSlice[];
}

/**
 * Slices of a confirmed universal Mach-O, or null for every other input.
 * FAT-shaped bytes that are not confirmed Mach-O (a JVM class, a table with
 * invalid ranges) stay with the thin reader, which reports them itself.
 */
export const universalMachoSlices = (bytes: Buffer): UniversalMacho | null => {
  const header = readFatContainerHeader(bytes, bytes.length);
  if (header.state !== "parsed") return null;
  const identity = classifyFatContainerIdentity(header, (offset) => {
    if (offset >= bytes.length) return undefined;
    if (offset + 4 > bytes.length) return null;
    return bytes.readUInt32BE(offset);
  });
  if (identity.state !== "mach-o") return null;
  return {
    magic: header.magic,
    wide: header.wide,
    slices: header.slices.map((slice) => {
      const thin = bytes.subarray(slice.offset, slice.offset + slice.size);
      return {
        index: slice.index,
        file_offset: slice.offset,
        file_bytes: slice.size,
        cpu_type: slice.cpuType,
        cpu_subtype: slice.cpuSubtype,
        bytes: thin,
        identity_failure: embeddedIdentityFailure(slice, thin),
      };
    }),
  };
};

const embeddedIdentityFailure = (
  slice: FatSliceDeclaration,
  thin: Buffer,
): string | null => {
  if (thin.length < 12)
    return `FAT architecture ${slice.index} is too short for a Mach-O header`;
  const magic = thin.readUInt32BE(0);
  const little = MACHO_LITTLE.includes(magic);
  if (!little && !MACHO_BIG.includes(magic))
    return `FAT architecture ${slice.index} does not start with a Mach-O header`;
  const word = (at: number) =>
    little ? thin.readUInt32LE(at) : thin.readUInt32BE(at);
  return validateFatSliceIdentity(slice, {
    cpuType: word(4),
    cpuSubtype: word(8),
  });
};
