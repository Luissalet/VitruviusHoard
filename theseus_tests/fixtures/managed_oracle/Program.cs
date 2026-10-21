using System;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization.Metadata;

// Independent oracle: CLI header, metadata rows and decoded IL tokens read with the runtime's System.Reflection.Metadata only.
// Usage: ManagedOracle <pe-file> <output.json>
public static class Oracle
{
    static MetadataReader md;
    static PEReader pe;
    static readonly Dictionary<ushort, OpCode> Ops = BuildOps();
    static readonly JsonArray OpcodeMismatches = new JsonArray();
    static readonly HashSet<string> CallOps = new HashSet<string> { "call", "callvirt", "newobj", "ldftn", "ldvirtftn", "jmp" };
    static readonly HashSet<string> FieldOps = new HashSet<string> { "ldfld", "stfld", "ldsfld", "stsfld", "ldflda", "ldsflda" };

    public static int Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--emit")
        {
            Synthetic.Write(args[1]);
            return 0;
        }
        using var stream = new FileStream(args[0], FileMode.Open, FileAccess.Read, FileShare.Read);
        pe = new PEReader(stream);
        md = pe.GetMetadataReader();
        var root = new JsonObject();
        root["pe"] = PeInfo();
        root["cli"] = Cli();
        root["metadata_version"] = md.MetadataVersion;
        root["table_row_counts"] = Tables();
        root["module"] = Module();
        root["assembly"] = md.IsAssembly ? Assembly() : null;
        root["assembly_refs"] = AssemblyRefs();
        root["type_refs"] = TypeRefs();
        root["type_defs"] = TypeDefs();
        root["fields"] = Fields();
        var strings = new SortedDictionary<int, string>();
        root["methods"] = Methods(strings);
        root["member_refs"] = MemberRefs();
        root["method_specs"] = MethodSpecs();
        root["type_specs"] = TypeSpecs();
        root["custom_attributes"] = CustomAttributes();
        root["module_refs"] = ModuleRefs();
        root["resources"] = Resources();
        root["files"] = Files();
        root["exported_types"] = ExportedTypes();
        root["generic_params"] = GenericParams();
        root["user_strings"] = UserStrings(strings);
        root["target_frameworks"] = TargetFrameworks();
        root["opcode_table_mismatches"] = OpcodeMismatches;
        root["opcode_names"] = new JsonArray(Ops.Values.Select(x => (JsonNode)x.Name).OrderBy(x => x.ToString(), StringComparer.Ordinal).ToArray());
        var options = new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping, TypeInfoResolver = new DefaultJsonTypeInfoResolver() };
        File.WriteAllText(args[1], root.ToJsonString(options), new UTF8Encoding(false));
        return 0;
    }

    static string Hex(byte[] bytes) => Convert.ToHexString(bytes).ToLowerInvariant();
    static string Sha(byte[] bytes) => Hex(SHA256.HashData(bytes));
    static string Tok(Handle handle) => handle.IsNil ? null : "0x" + MetadataTokens.GetToken(handle).ToString("x8");
    static string Str(StringHandle handle) => handle.IsNil ? null : md.GetString(handle);
    static string Guid(GuidHandle handle) => handle.IsNil ? null : md.GetGuid(handle).ToString("D");
    static string Blob(BlobHandle handle) => Hex(md.GetBlobBytes(handle));

    static Dictionary<ushort, OpCode> BuildOps()
    {
        var table = new Dictionary<ushort, OpCode>();
        foreach (var field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
            if (field.GetValue(null) is OpCode op && !op.Name.StartsWith("prefix")) table[(ushort)op.Value] = op;
        return table;
    }

    static JsonObject PeInfo()
    {
        var headers = pe.PEHeaders;
        return new JsonObject
        {
            ["machine"] = (int)headers.CoffHeader.Machine,
            ["magic"] = (int)headers.PEHeader.Magic,
            ["characteristics"] = (int)headers.CoffHeader.Characteristics,
            ["section_count"] = headers.SectionHeaders.Length,
        };
    }

    static JsonObject Directory(DirectoryEntry entry) => new JsonObject { ["rva"] = entry.RelativeVirtualAddress, ["size"] = entry.Size };

    static JsonObject Cli()
    {
        var cor = pe.PEHeaders.CorHeader;
        return new JsonObject
        {
            ["header_offset"] = pe.PEHeaders.CorHeaderStartOffset,
            ["flags"] = (int)cor.Flags,
            ["runtime_version"] = cor.MajorRuntimeVersion + "." + cor.MinorRuntimeVersion,
            ["entry_point"] = cor.EntryPointTokenOrRelativeVirtualAddress,
            ["metadata"] = Directory(cor.MetadataDirectory),
            ["resources"] = Directory(cor.ResourcesDirectory),
            ["strong_name"] = Directory(cor.StrongNameSignatureDirectory),
            ["managed_native_header"] = Directory(cor.ManagedNativeHeaderDirectory),
            ["vtable_fixups"] = Directory(cor.VtableFixupsDirectory),
        };
    }

    static JsonObject Tables()
    {
        var counts = new JsonObject();
        foreach (var table in Enum.GetValues<TableIndex>())
        {
            int rows;
            try { rows = md.GetTableRowCount(table); } catch (ArgumentOutOfRangeException) { continue; }
            if (rows > 0) counts[table.ToString()] = rows;
        }
        return counts;
    }

    static JsonObject Module()
    {
        var module = md.GetModuleDefinition();
        return new JsonObject
        {
            ["name"] = md.GetString(module.Name),
            ["mvid"] = Guid(module.Mvid),
            ["generation"] = module.Generation,
            ["enc_id"] = Guid(module.GenerationId),
            ["enc_base_id"] = Guid(module.BaseGenerationId),
        };
    }

    static string KeyToken(byte[] key)
    {
        var hash = SHA1.HashData(key);
        return Hex(hash.Skip(hash.Length - 8).Reverse().ToArray());
    }

    static JsonObject KeyInfo(byte[] bytes, bool isKey) => new JsonObject
    {
        ["kind"] = bytes.Length == 0 ? "none" : isKey ? "public-key" : "public-key-token",
        ["byte_length"] = bytes.Length,
        ["sha256"] = bytes.Length == 0 ? null : Sha(bytes),
        ["token"] = bytes.Length == 0 ? null : isKey ? KeyToken(bytes) : Hex(bytes),
    };

    static JsonObject Assembly()
    {
        var assembly = md.GetAssemblyDefinition();
        return new JsonObject
        {
            ["name"] = md.GetString(assembly.Name),
            ["version"] = assembly.Version.ToString(),
            ["culture"] = Str(assembly.Culture),
            ["flags"] = (int)assembly.Flags,
            ["hash_algorithm"] = (long)(uint)assembly.HashAlgorithm,
            ["public_key"] = KeyInfo(md.GetBlobBytes(assembly.PublicKey), true),
        };
    }

    static JsonArray AssemblyRefs()
    {
        var rows = new JsonArray();
        foreach (var handle in md.AssemblyReferences)
        {
            var reference = md.GetAssemblyReference(handle);
            bool isKey = (reference.Flags & AssemblyFlags.PublicKey) != 0;
            var hash = md.GetBlobBytes(reference.HashValue);
            rows.Add(new JsonObject
            {
                ["token"] = Tok(handle),
                ["name"] = md.GetString(reference.Name),
                ["version"] = reference.Version.ToString(),
                ["culture"] = Str(reference.Culture),
                ["flags"] = (int)reference.Flags,
                ["public_key_or_token"] = KeyInfo(md.GetBlobBytes(reference.PublicKeyOrToken), isKey),
                ["hash_value_length"] = hash.Length,
                ["hash_value_sha256"] = hash.Length == 0 ? null : Sha(hash),
            });
        }
        return rows;
    }

    static string TypeRefName(TypeReferenceHandle handle)
    {
        var reference = md.GetTypeReference(handle);
        string ns = md.GetString(reference.Namespace), name = md.GetString(reference.Name);
        if (reference.ResolutionScope.Kind == HandleKind.TypeReference)
            return TypeRefName((TypeReferenceHandle)reference.ResolutionScope) + "+" + name;
        return ns.Length > 0 ? ns + "." + name : name;
    }

    static string TypeDefName(TypeDefinitionHandle handle)
    {
        var definition = md.GetTypeDefinition(handle);
        string ns = md.GetString(definition.Namespace), name = md.GetString(definition.Name);
        var outer = definition.GetDeclaringType();
        if (!outer.IsNil) return TypeDefName(outer) + "+" + name;
        return ns.Length > 0 ? ns + "." + name : name;
    }

    static string EntityName(EntityHandle handle) => handle.Kind switch
    {
        HandleKind.TypeDefinition => TypeDefName((TypeDefinitionHandle)handle),
        HandleKind.TypeReference => TypeRefName((TypeReferenceHandle)handle),
        _ => null,
    };

    static JsonArray TypeRefs()
    {
        var rows = new JsonArray();
        foreach (var handle in md.TypeReferences)
        {
            var reference = md.GetTypeReference(handle);
            rows.Add(new JsonObject
            {
                ["token"] = Tok(handle),
                ["scope"] = Tok(reference.ResolutionScope),
                ["namespace"] = md.GetString(reference.Namespace),
                ["name"] = md.GetString(reference.Name),
                ["full_name"] = TypeRefName(handle),
            });
        }
        return rows;
    }

    static JsonArray Rows(IEnumerable<EntityHandle> handles)
    {
        var rows = new JsonArray();
        foreach (var handle in handles) rows.Add(MetadataTokens.GetRowNumber(handle));
        return rows;
    }

    static JsonArray TypeDefs()
    {
        var rows = new JsonArray();
        foreach (var handle in md.TypeDefinitions)
        {
            var type = md.GetTypeDefinition(handle);
            var layout = type.GetLayout();
            rows.Add(new JsonObject
            {
                ["token"] = Tok(handle),
                ["namespace"] = md.GetString(type.Namespace),
                ["name"] = md.GetString(type.Name),
                ["full_name"] = TypeDefName(handle),
                ["flags"] = (int)type.Attributes,
                ["extends"] = Tok(type.BaseType),
                ["enclosing"] = Tok(type.GetDeclaringType()),
                ["field_rows"] = Rows(type.GetFields().Select(x => (EntityHandle)x)),
                ["method_rows"] = Rows(type.GetMethods().Select(x => (EntityHandle)x)),
                ["generic_param_count"] = type.GetGenericParameters().Count,
                ["interface_count"] = type.GetInterfaceImplementations().Count,
                ["method_impl_count"] = type.GetMethodImplementations().Count,
                ["layout"] = layout.IsDefault ? null : new JsonObject { ["pack"] = layout.PackingSize, ["size"] = layout.Size },
            });
        }
        return rows;
    }

    static JsonArray Fields()
    {
        var rows = new JsonArray();
        foreach (var handle in md.FieldDefinitions)
        {
            var field = md.GetFieldDefinition(handle);
            rows.Add(new JsonObject
            {
                ["token"] = Tok(handle),
                ["declaring_type"] = Tok(field.GetDeclaringType()),
                ["name"] = md.GetString(field.Name),
                ["flags"] = (int)field.Attributes,
                ["signature"] = Blob(field.Signature),
                ["decoded"] = DecodedField(field.DecodeSignature(Provider.Instance, null)),
                ["rva"] = field.GetRelativeVirtualAddress(),
                ["offset"] = field.GetOffset(),
                ["has_default"] = !field.GetDefaultValue().IsNil,
                ["has_marshalling"] = !field.GetMarshallingDescriptor().IsNil,
            });
        }
        return rows;
    }

    static JsonArray Methods(SortedDictionary<int, string> strings)
    {
        var rows = new JsonArray();
        foreach (var handle in md.MethodDefinitions)
        {
            var method = md.GetMethodDefinition(handle);
            var import = method.GetImport();
            var row = new JsonObject
            {
                ["token"] = Tok(handle),
                ["declaring_type"] = Tok(method.GetDeclaringType()),
                ["name"] = md.GetString(method.Name),
                ["rva"] = method.RelativeVirtualAddress,
                ["flags"] = (int)method.Attributes,
                ["impl_flags"] = (int)method.ImplAttributes,
                ["signature"] = Blob(method.Signature),
                ["decoded"] = DecodedMethod(method.DecodeSignature(Provider.Instance, null)),
                ["param_count"] = method.GetParameters().Count,
                ["generic_param_count"] = method.GetGenericParameters().Count,
                ["import"] = import.Module.IsNil ? null : new JsonObject
                {
                    ["name"] = md.GetString(import.Name),
                    ["module"] = Tok(import.Module),
                    ["module_name"] = md.GetString(md.GetModuleReference(import.Module).Name),
                    ["attributes"] = (int)import.Attributes,
                    ["exact_spelling"] = import.Attributes.HasFlag(MethodImportAttributes.ExactSpelling),
                    ["set_last_error"] = import.Attributes.HasFlag(MethodImportAttributes.SetLastError),
                    ["char_set"] = (import.Attributes & MethodImportAttributes.CharSetMask) switch
                    {
                        MethodImportAttributes.None => "not-specified",
                        MethodImportAttributes.CharSetAnsi => "ansi",
                        MethodImportAttributes.CharSetUnicode => "unicode",
                        MethodImportAttributes.CharSetAuto => "auto",
                        _ => "unknown",
                    },
                    ["call_convention"] = (import.Attributes & MethodImportAttributes.CallingConventionMask) switch
                    {
                        MethodImportAttributes.None => "not-specified",
                        MethodImportAttributes.CallingConventionWinApi => "winapi",
                        MethodImportAttributes.CallingConventionCDecl => "cdecl",
                        MethodImportAttributes.CallingConventionStdCall => "stdcall",
                        MethodImportAttributes.CallingConventionThisCall => "thiscall",
                        MethodImportAttributes.CallingConventionFastCall => "fastcall",
                        _ => "unknown",
                    },
                    ["best_fit"] = (import.Attributes & MethodImportAttributes.BestFitMappingMask) switch
                    {
                        MethodImportAttributes.None => "assembly-default",
                        MethodImportAttributes.BestFitMappingEnable => "enabled",
                        MethodImportAttributes.BestFitMappingDisable => "disabled",
                        _ => "unknown",
                    },
                    ["throw_on_unmappable_char"] = (import.Attributes & MethodImportAttributes.ThrowOnUnmappableCharMask) switch
                    {
                        MethodImportAttributes.None => "assembly-default",
                        MethodImportAttributes.ThrowOnUnmappableCharEnable => "enabled",
                        MethodImportAttributes.ThrowOnUnmappableCharDisable => "disabled",
                        _ => "unknown",
                    },
                },
                ["body"] = method.RelativeVirtualAddress == 0 ? null : Body(method.RelativeVirtualAddress, strings),
            };
            rows.Add(row);
        }
        return rows;
    }

    static JsonObject Body(int rva, SortedDictionary<int, string> strings)
    {
        var body = pe.GetMethodBody(rva);
        var il = body.GetILBytes();
        byte first = pe.GetSectionData(rva).GetContent(0, 1)[0];
        var calls = new JsonArray();
        var fields = new JsonArray();
        var instructions = new JsonArray();
        var counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
        var callTokens = new SortedSet<string>(StringComparer.Ordinal);
        var fieldTokens = new SortedSet<string>(StringComparer.Ordinal);
        for (int i = 0; i < il.Length;)
        {
            int start = i;
            ushort key = il[i++];
            if (key == 0xFE) key = (ushort)(0xFE00 | il[i++]);
            if (!Ops.TryGetValue(key, out var op)) throw new InvalidDataException("unknown opcode 0x" + key.ToString("x") + " at " + start);
            int size;
            switch (op.OperandType)
            {
                case OperandType.InlineNone: size = 0; break;
                case OperandType.ShortInlineBrTarget:
                case OperandType.ShortInlineI:
                case OperandType.ShortInlineVar: size = 1; break;
                case OperandType.InlineVar: size = 2; break;
                case OperandType.InlineBrTarget:
                case OperandType.InlineField:
                case OperandType.InlineI:
                case OperandType.InlineMethod:
                case OperandType.InlineSig:
                case OperandType.InlineString:
                case OperandType.InlineTok:
                case OperandType.InlineType:
                case OperandType.ShortInlineR: size = 4; break;
                case OperandType.InlineI8:
                case OperandType.InlineR: size = 8; break;
                case OperandType.InlineSwitch: size = 4 + 4 * BitConverter.ToInt32(il, i); break;
                default: throw new InvalidDataException("operand type " + op.OperandType);
            }
            string operand = null;
            switch (op.OperandType)
            {
                case OperandType.InlineField:
                case OperandType.InlineMethod:
                case OperandType.InlineSig:
                case OperandType.InlineString:
                case OperandType.InlineTok:
                case OperandType.InlineType:
                    int token = BitConverter.ToInt32(il, i);
                    operand = "0x" + token.ToString("x8");
                    if (op.OperandType == OperandType.InlineString && !strings.ContainsKey(token & 0xFFFFFF))
                        strings[token & 0xFFFFFF] = md.GetUserString(MetadataTokens.UserStringHandle(token & 0xFFFFFF));
                    var site = new JsonObject { ["il_offset"] = start, ["opcode"] = op.Name, ["token"] = operand };
                    if (CallOps.Contains(op.Name)) { calls.Add(site); callTokens.Add(operand); }
                    else if (FieldOps.Contains(op.Name)) { fields.Add(site.DeepClone()); fieldTokens.Add(operand); }
                    break;
                // Branch operands are reported as absolute IL offsets, switch as its case count, numbers in invariant text.
                case OperandType.ShortInlineBrTarget: operand = (i + 1 + (sbyte)il[i]).ToString(); break;
                case OperandType.InlineBrTarget: operand = (i + 4 + BitConverter.ToInt32(il, i)).ToString(); break;
                case OperandType.ShortInlineI: operand = op.Name == "ldc.i4.s" ? ((sbyte)il[i]).ToString() : il[i].ToString(); break;
                case OperandType.ShortInlineVar: operand = il[i].ToString(); break;
                case OperandType.InlineVar: operand = BitConverter.ToUInt16(il, i).ToString(); break;
                case OperandType.InlineI: operand = BitConverter.ToInt32(il, i).ToString(); break;
                case OperandType.InlineI8: operand = BitConverter.ToInt64(il, i).ToString(); break;
                case OperandType.ShortInlineR: operand = BitConverter.ToSingle(il, i).ToString("R", System.Globalization.CultureInfo.InvariantCulture); break;
                case OperandType.InlineR: operand = BitConverter.ToDouble(il, i).ToString("R", System.Globalization.CultureInfo.InvariantCulture); break;
                case OperandType.InlineSwitch: operand = BitConverter.ToInt32(il, i).ToString(); break;
            }
            counts[op.Name] = counts.GetValueOrDefault(op.Name) + 1;
            instructions.Add(new JsonObject
            {
                ["il_offset"] = start,
                ["opcode"] = op.Name,
                ["operand"] = operand,
                ["bytes"] = Hex(il.AsSpan(start, i + size - start).ToArray()),
            });
            i += size;
        }
        var regions = new JsonArray();
        foreach (var region in body.ExceptionRegions)
            regions.Add(new JsonObject
            {
                ["kind"] = (int)region.Kind,
                ["try_offset"] = region.TryOffset,
                ["try_length"] = region.TryLength,
                ["handler_offset"] = region.HandlerOffset,
                ["handler_length"] = region.HandlerLength,
                ["catch_type"] = Tok(region.CatchType),
                ["filter_offset"] = region.FilterOffset,
            });
        var opcodeCounts = new JsonObject();
        foreach (var pair in counts) opcodeCounts[pair.Key] = pair.Value;
        return new JsonObject
        {
            ["header_format"] = (first & 3) == 2 ? "tiny" : "fat",
            ["il_size"] = il.Length,
            ["il_sha256"] = Sha(il),
            ["max_stack"] = body.MaxStack,
            ["init_locals"] = body.LocalVariablesInitialized,
            ["local_signature"] = Tok(body.LocalSignature),
            ["body_size"] = body.Size,
            ["eh_format"] = EhFormat(rva, body, (first & 3) == 2),
            ["instruction_count"] = instructions.Count,
            ["opcode_counts"] = opcodeCounts,
            ["call_sites"] = calls,
            ["call_tokens"] = new JsonArray(callTokens.Select(x => (JsonNode)x).ToArray()),
            ["field_sites"] = fields,
            ["field_tokens"] = new JsonArray(fieldTokens.Select(x => (JsonNode)x).ToArray()),
            ["instructions"] = instructions,
            ["exception_regions"] = regions,
        };
    }

    // "small" or "fat" for the exception clause table that follows the IL (ECMA-335 II.25.4.5), null without one.
    static string EhFormat(int rva, MethodBodyBlock body, bool tiny)
    {
        if (tiny || body.ExceptionRegions.IsEmpty) return null;
        var raw = pe.GetSectionData(rva).GetContent(0, body.Size);
        int headerSize = ((raw[0] | (raw[1] << 8)) >> 12) * 4;
        int at = (headerSize + body.GetILBytes().Length + 3) & ~3;
        return (raw[at] & 0x40) != 0 ? "fat" : "small";
    }

    static JsonArray MemberRefs()
    {
        var rows = new JsonArray();
        foreach (var handle in md.MemberReferences)
        {
            var member = md.GetMemberReference(handle);
            rows.Add(new JsonObject
            {
                ["token"] = Tok(handle),
                ["parent"] = Tok(member.Parent),
                ["parent_name"] = member.Parent.Kind == HandleKind.TypeReference || member.Parent.Kind == HandleKind.TypeDefinition ? EntityName(member.Parent) : null,
                ["parent_generic_type"] = member.Parent.Kind == HandleKind.TypeSpecification ? GenericDefinition((TypeSpecificationHandle)member.Parent) : null,
                ["name"] = md.GetString(member.Name),
                ["kind"] = member.GetKind().ToString(),
                ["signature"] = Blob(member.Signature),
                ["decoded"] = member.GetKind() == MemberReferenceKind.Method
                    ? DecodedMethod(member.DecodeMethodSignature(Provider.Instance, null))
                    : DecodedField(member.DecodeFieldSignature(Provider.Instance, null)),
            });
        }
        return rows;
    }

    // The generic type definition named by a TypeSpec GENERICINST blob; null for every other TypeSpec shape.
    static string GenericDefinition(TypeSpecificationHandle handle)
    {
        var reader = md.GetBlobReader(md.GetTypeSpecification(handle).Signature);
        if (reader.ReadByte() != 0x15) return null;
        byte kind = reader.ReadByte();
        return kind == 0x11 || kind == 0x12 ? Tok(reader.ReadTypeHandle()) : null;
    }

    static JsonArray MethodSpecs()
    {
        var rows = new JsonArray();
        for (int row = 1; row <= md.GetTableRowCount(TableIndex.MethodSpec); row++)
        {
            var handle = MetadataTokens.MethodSpecificationHandle(row);
            var spec = md.GetMethodSpecification(handle);
            rows.Add(new JsonObject { ["token"] = Tok(handle), ["method"] = Tok(spec.Method), ["signature"] = Blob(spec.Signature) });
        }
        return rows;
    }

    static JsonArray TypeSpecs()
    {
        var rows = new JsonArray();
        for (int row = 1; row <= md.GetTableRowCount(TableIndex.TypeSpec); row++)
        {
            var handle = MetadataTokens.TypeSpecificationHandle(row);
            rows.Add(new JsonObject { ["token"] = Tok(handle), ["signature"] = Blob(md.GetTypeSpecification(handle).Signature) });
        }
        return rows;
    }

    static JsonArray CustomAttributes()
    {
        var rows = new JsonArray();
        foreach (var handle in md.CustomAttributes)
        {
            var attribute = md.GetCustomAttribute(handle);
            var value = md.GetBlobBytes(attribute.Value);
            string typeName = null;
            if (attribute.Constructor.Kind == HandleKind.MethodDefinition)
                typeName = TypeDefName(md.GetMethodDefinition((MethodDefinitionHandle)attribute.Constructor).GetDeclaringType());
            else if (attribute.Constructor.Kind == HandleKind.MemberReference)
                typeName = EntityName(md.GetMemberReference((MemberReferenceHandle)attribute.Constructor).Parent);
            rows.Add(new JsonObject
            {
                ["token"] = Tok(handle),
                ["parent"] = Tok(attribute.Parent),
                ["constructor"] = Tok(attribute.Constructor),
                ["type_name"] = typeName,
                ["value_length"] = value.Length,
                ["value_sha256"] = Sha(value),
            });
        }
        return rows;
    }

    static JsonArray ModuleRefs()
    {
        var rows = new JsonArray();
        for (int row = 1; row <= md.GetTableRowCount(TableIndex.ModuleRef); row++)
        {
            var handle = MetadataTokens.ModuleReferenceHandle(row);
            rows.Add(new JsonObject { ["token"] = Tok(handle), ["name"] = md.GetString(md.GetModuleReference(handle).Name) });
        }
        return rows;
    }

    static JsonArray Resources()
    {
        var rows = new JsonArray();
        foreach (var handle in md.ManifestResources)
        {
            var resource = md.GetManifestResource(handle);
            bool embedded = resource.Implementation.IsNil;
            byte[] data = null;
            if (embedded)
            {
                var block = pe.GetSectionData(pe.PEHeaders.CorHeader.ResourcesDirectory.RelativeVirtualAddress);
                var reader = block.GetReader((int)resource.Offset, block.Length - (int)resource.Offset);
                data = reader.ReadBytes(reader.ReadInt32());
            }
            rows.Add(new JsonObject
            {
                ["token"] = Tok(handle),
                ["name"] = md.GetString(resource.Name),
                ["flags"] = (int)resource.Attributes,
                ["offset"] = resource.Offset,
                ["implementation"] = Tok(resource.Implementation),
                ["embedded"] = embedded,
                ["data_length"] = data?.Length,
                ["data_sha256"] = data == null ? null : Sha(data),
            });
        }
        return rows;
    }

    static JsonArray Files()
    {
        var rows = new JsonArray();
        foreach (var handle in md.AssemblyFiles)
        {
            var file = md.GetAssemblyFile(handle);
            rows.Add(new JsonObject { ["token"] = Tok(handle), ["name"] = md.GetString(file.Name), ["contains_metadata"] = file.ContainsMetadata, ["hash_sha256"] = Sha(md.GetBlobBytes(file.HashValue)) });
        }
        return rows;
    }

    static JsonArray ExportedTypes()
    {
        var rows = new JsonArray();
        foreach (var handle in md.ExportedTypes)
        {
            var exported = md.GetExportedType(handle);
            rows.Add(new JsonObject
            {
                ["token"] = Tok(handle),
                ["namespace"] = md.GetString(exported.Namespace),
                ["name"] = md.GetString(exported.Name),
                ["flags"] = (int)exported.Attributes,
                ["implementation"] = Tok(exported.Implementation),
                ["type_def_id"] = exported.GetTypeDefinitionId(),
            });
        }
        return rows;
    }

    static JsonArray GenericParams()
    {
        var rows = new JsonArray();
        foreach (var handle in HandlesOf(md.GetTableRowCount(TableIndex.GenericParam)))
        {
            var parameter = md.GetGenericParameter(handle);
            var constraints = new JsonArray();
            foreach (var constraint in parameter.GetConstraints()) constraints.Add(Tok(md.GetGenericParameterConstraint(constraint).Type));
            rows.Add(new JsonObject
            {
                ["token"] = Tok(handle),
                ["parent"] = Tok(parameter.Parent),
                ["index"] = parameter.Index,
                ["name"] = md.GetString(parameter.Name),
                ["flags"] = (int)parameter.Attributes,
                ["constraints"] = constraints,
            });
        }
        return rows;
    }

    static IEnumerable<GenericParameterHandle> HandlesOf(int rows)
    {
        for (int row = 1; row <= rows; row++) yield return MetadataTokens.GenericParameterHandle(row);
    }

    static string Convention(SignatureHeader header)
    {
        string name = header.CallingConvention switch
        {
            SignatureCallingConvention.Default => "default",
            SignatureCallingConvention.CDecl => "c",
            SignatureCallingConvention.StdCall => "stdcall",
            SignatureCallingConvention.ThisCall => "thiscall",
            SignatureCallingConvention.FastCall => "fastcall",
            SignatureCallingConvention.VarArgs => "vararg",
            SignatureCallingConvention.Unmanaged => "unmanaged",
            _ => "unknown:" + (int)header.CallingConvention,
        };
        var flags = new List<string>();
        if (header.IsInstance) flags.Add("has-this");
        if (header.HasExplicitThis) flags.Add("explicit-this");
        if (header.IsGeneric) flags.Add("generic");
        return flags.Count == 0 ? name : name + " " + string.Join(" ", flags);
    }

    static JsonObject DecodedMethod(MethodSignature<Ty> signature) => new JsonObject
    {
        ["kind"] = "method",
        ["convention"] = Convention(signature.Header),
        ["parameter_count"] = signature.ParameterTypes.Length,
        ["generic_parameter_count"] = signature.Header.IsGeneric ? (JsonNode)signature.GenericParameterCount : null,
        ["return_type"] = signature.ReturnType.ToString(),
        ["parameter_types"] = new JsonArray(signature.ParameterTypes.Select(x => (JsonNode)x.ToString()).ToArray()),
    };

    static JsonObject DecodedField(Ty type) => new JsonObject { ["kind"] = "field", ["convention"] = "field", ["field_type"] = type.ToString() };

    static bool EcmaTerminal(string value)
    {
        // ECMA-335 II.24.2.4: 1 when any character has a non-zero high byte or a low byte in 01-08, 0E-1F, 27, 2D, 7F.
        foreach (char c in value)
        {
            int low = c & 0xFF;
            if ((c >> 8) != 0 || (low >= 1 && low <= 8) || (low >= 0x0E && low <= 0x1F) || low == 0x27 || low == 0x2D || low == 0x7F) return true;
        }
        return false;
    }

    static JsonArray UserStrings(SortedDictionary<int, string> referenced)
    {
        var heap = pe.GetMetadata().GetContent();
        int start = md.GetHeapMetadataOffset(HeapIndex.UserString), size = md.GetHeapSize(HeapIndex.UserString);
        var rows = new JsonArray();
        for (int offset = 1; offset < size;)
        {
            int at = start + offset, length, prefix;
            byte b = heap[at];
            if ((b & 0x80) == 0) { length = b; prefix = 1; }
            else if ((b & 0xC0) == 0x80) { length = ((b & 0x3F) << 8) | heap[at + 1]; prefix = 2; }
            else { length = ((b & 0x1F) << 24) | (heap[at + 1] << 16) | (heap[at + 2] << 8) | heap[at + 3]; prefix = 4; }
            if (length == 0) { offset += prefix; continue; }
            string value = md.GetUserString(MetadataTokens.UserStringHandle(offset));
            rows.Add(new JsonObject
            {
                ["token"] = "0x" + (0x70000000 | offset).ToString("x8"),
                ["offset"] = offset,
                ["value"] = value,
                ["terminal_byte"] = heap[at + prefix + length - 1],
                ["ecma_terminal"] = EcmaTerminal(value) ? 1 : 0,
                ["referenced_by_ldstr"] = referenced.ContainsKey(offset),
            });
            offset += prefix + length;
        }
        return rows;
    }

    static JsonArray TargetFrameworks()
    {
        var found = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var handle in md.GetAssemblyDefinition().GetCustomAttributes())
        {
            var attribute = md.GetCustomAttribute(handle);
            if (attribute.Constructor.Kind != HandleKind.MemberReference && attribute.Constructor.Kind != HandleKind.MethodDefinition) continue;
            var parent = attribute.Constructor.Kind == HandleKind.MemberReference
                ? EntityName(md.GetMemberReference((MemberReferenceHandle)attribute.Constructor).Parent)
                : TypeDefName(md.GetMethodDefinition((MethodDefinitionHandle)attribute.Constructor).GetDeclaringType());
            if (parent != "System.Runtime.Versioning.TargetFrameworkAttribute") continue;
            var reader = md.GetBlobReader(attribute.Value);
            if (reader.ReadUInt16() == 1) found.Add(reader.ReadSerializedString());
        }
        return new JsonArray(found.Select(x => (JsonNode)x).ToArray());
    }

    static Oracle()
    {
        foreach (var pair in Ops)
        {
            if (!Enum.IsDefined(typeof(ILOpCode), pair.Key)) { OpcodeMismatches.Add("undefined ILOpCode 0x" + pair.Key.ToString("x")); continue; }
            string expected = ((ILOpCode)pair.Key).ToString().Replace('_', '.').ToLowerInvariant();
            if (expected != pair.Value.Name.TrimEnd('.')) OpcodeMismatches.Add(expected + " != " + pair.Value.Name);
        }
    }
}

// A decoded type rendered as: primitive name, "class:N" / "valuetype:N" (N = TypeDefOrRef coded index), "var:N", "mvar:N",
// suffixes * & [], array shapes "[lo...hi,size]", generic instantiations "class:N<a,b>", "fnptr[convention](params)->ret",
// and custom modifiers "modreq:N" / "modopt:N" appended in source order.
public sealed class Ty
{
    public string Base;
    public int Coded;
    public List<string> Mods = new List<string>();
    public override string ToString() => Mods.Count == 0 ? Base : Base + " " + string.Join(" ", Mods);
}

public sealed class Provider : ISignatureTypeProvider<Ty, object>
{
    public static readonly Provider Instance = new Provider();

    static int Coded(EntityHandle handle, int tag) => (MetadataTokens.GetRowNumber(handle) << 2) | tag;
    static string Kind(byte raw) => raw == 0x11 ? "valuetype" : "class";

    public Ty GetPrimitiveType(PrimitiveTypeCode code) => new Ty
    {
        Base = code switch
        {
            PrimitiveTypeCode.Void => "void",
            PrimitiveTypeCode.Boolean => "bool",
            PrimitiveTypeCode.Char => "char",
            PrimitiveTypeCode.SByte => "i1",
            PrimitiveTypeCode.Byte => "u1",
            PrimitiveTypeCode.Int16 => "i2",
            PrimitiveTypeCode.UInt16 => "u2",
            PrimitiveTypeCode.Int32 => "i4",
            PrimitiveTypeCode.UInt32 => "u4",
            PrimitiveTypeCode.Int64 => "i8",
            PrimitiveTypeCode.UInt64 => "u8",
            PrimitiveTypeCode.Single => "r4",
            PrimitiveTypeCode.Double => "r8",
            PrimitiveTypeCode.String => "string",
            PrimitiveTypeCode.IntPtr => "native-int",
            PrimitiveTypeCode.UIntPtr => "native-uint",
            PrimitiveTypeCode.Object => "object",
            PrimitiveTypeCode.TypedReference => "typedbyref",
            _ => throw new InvalidDataException("primitive " + code),
        },
    };

    public Ty GetTypeFromDefinition(MetadataReader reader, TypeDefinitionHandle handle, byte rawTypeKind)
        => new Ty { Coded = Coded(handle, 0), Base = Kind(rawTypeKind) + ":" + Coded(handle, 0) };

    public Ty GetTypeFromReference(MetadataReader reader, TypeReferenceHandle handle, byte rawTypeKind)
        => new Ty { Coded = Coded(handle, 1), Base = Kind(rawTypeKind) + ":" + Coded(handle, 1) };

    public Ty GetTypeFromSpecification(MetadataReader reader, object context, TypeSpecificationHandle handle, byte rawTypeKind)
        => new Ty { Coded = Coded(handle, 2), Base = Kind(rawTypeKind) + ":" + Coded(handle, 2) };

    public Ty GetSZArrayType(Ty element) => new Ty { Base = element + "[]" };
    public Ty GetByReferenceType(Ty element) => new Ty { Base = element + "&" };
    public Ty GetPointerType(Ty element) => new Ty { Base = element + "*" };
    public Ty GetGenericTypeParameter(object context, int index) => new Ty { Base = "var:" + index };
    public Ty GetGenericMethodParameter(object context, int index) => new Ty { Base = "mvar:" + index };
    public Ty GetPinnedType(Ty element) => element;

    public Ty GetGenericInstantiation(Ty generic, ImmutableArray<Ty> arguments)
        => new Ty { Base = generic + "<" + string.Join(",", arguments.Select(x => x.ToString())) + ">" };

    public Ty GetArrayType(Ty element, ArrayShape shape)
    {
        var dimensions = new List<string>();
        for (int index = 0; index < shape.Rank; index++)
        {
            bool hasLower = index < shape.LowerBounds.Length, hasSize = index < shape.Sizes.Length;
            if (hasLower) dimensions.Add(hasSize ? shape.LowerBounds[index] + "..." + (shape.LowerBounds[index] + shape.Sizes[index] - 1) : shape.LowerBounds[index] + "...");
            else if (hasSize) dimensions.Add(shape.Sizes[index].ToString());
            else dimensions.Add(shape.Rank == 1 ? "..." : "");
        }
        return new Ty { Base = element + "[" + string.Join(",", dimensions) + "]" };
    }

    public Ty GetFunctionPointerType(MethodSignature<Ty> signature)
    {
        string head = Convention(signature.Header) + (signature.Header.IsGeneric ? ";" + signature.GenericParameterCount : "");
        // The header text mirrors the Oracle.Convention flags above.
        return new Ty { Base = "fnptr[" + head + "](" + string.Join(",", signature.ParameterTypes.Select(x => x.ToString())) + ")->" + signature.ReturnType };
    }

    public Ty GetModifiedType(Ty modifier, Ty unmodified, bool isRequired)
    {
        var result = new Ty { Base = unmodified.Base, Coded = unmodified.Coded };
        result.Mods.Add((isRequired ? "modreq:" : "modopt:") + modifier.Coded);
        result.Mods.AddRange(unmodified.Mods);
        return result;
    }

    static string Convention(SignatureHeader header)
    {
        string name = header.CallingConvention switch
        {
            SignatureCallingConvention.Default => "default",
            SignatureCallingConvention.CDecl => "c",
            SignatureCallingConvention.StdCall => "stdcall",
            SignatureCallingConvention.ThisCall => "thiscall",
            SignatureCallingConvention.FastCall => "fastcall",
            SignatureCallingConvention.VarArgs => "vararg",
            SignatureCallingConvention.Unmanaged => "unmanaged",
            _ => "unknown:" + (int)header.CallingConvention,
        };
        var flags = new List<string>();
        if (header.IsInstance) flags.Add("has-this");
        if (header.HasExplicitThis) flags.Add("explicit-this");
        if (header.IsGeneric) flags.Add("generic");
        return flags.Count == 0 ? name : name + " " + string.Join(" ", flags);
    }
}
