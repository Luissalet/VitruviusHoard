using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;

// "ManagedOracle --emit <out.dll>": writes an assembly with System.Reflection.Metadata's own writer so the test also covers
// what compilers never produce: every CIL opcode with each operand kind, fault/filter/catch/finally regions in the small and
// fat exception-table formats, a retargetable AssemblyRef carrying a full public key, a culture and a hash.
public static class Synthetic
{
    const int MethodDef = 0x06000001, FieldDef = 0x04000001, TypeDef = 0x02000002;

    public static byte[] Key()
    {
        var modulus = new byte[128];
        for (int i = 0; i < 4; i++) SHA256.HashData(new[] { (byte)i }).CopyTo(modulus, i * 32);
        modulus[0] |= 1;
        modulus[127] |= 0x80;
        var blob = new List<byte> { 6, 2, 0, 0, 0, 0x24, 0, 0, (byte)'R', (byte)'S', (byte)'A', (byte)'1' };
        blob.AddRange(BitConverter.GetBytes(1024));
        blob.AddRange(BitConverter.GetBytes(65537));
        blob.AddRange(modulus);
        var key = new List<byte>();
        key.AddRange(BitConverter.GetBytes(0x2400));
        key.AddRange(BitConverter.GetBytes(0x8004));
        key.AddRange(BitConverter.GetBytes(blob.Count));
        key.AddRange(blob);
        return key.ToArray();
    }

    static BlobHandle Sig(MetadataBuilder m, Action<BlobBuilder> write)
    {
        var builder = new BlobBuilder();
        write(builder);
        return m.GetOrAddBlob(builder);
    }

    public static void Write(string path)
    {
        var m = new MetadataBuilder();
        var code = new BlobBuilder();
        var bodies = new MethodBodyStreamEncoder(code);
        m.AddModule(0, m.GetOrAddString("synthetic.dll"), m.GetOrAddGuid(new Guid("0badc0de-1234-4abc-8def-001122334455")), default, default);
        m.AddAssembly(m.GetOrAddString("Synthetic"), new Version(9, 8, 7, 6), m.GetOrAddString("fr-FR"), m.GetOrAddBlob(Key()), AssemblyFlags.PublicKey, AssemblyHashAlgorithm.Sha1);
        var runtime = m.AddAssemblyReference(m.GetOrAddString("System.Runtime"), new Version(8, 0, 0, 0), default,
            m.GetOrAddBlob(new byte[] { 0xb0, 0x3f, 0x5f, 0x7f, 0x11, 0xd5, 0x0a, 0x3a }), default, default);
        var satellite = m.AddAssemblyReference(m.GetOrAddString("Lib.Satellite"), new Version(1, 2, 3, 4), m.GetOrAddString("en-US"), m.GetOrAddBlob(Key()),
            AssemblyFlags.PublicKey | AssemblyFlags.Retargetable, m.GetOrAddBlob(Enumerable.Range(1, 20).Select(x => (byte)x).ToArray()));
        m.AddAssemblyReference(m.GetOrAddString("NoKey"), new Version(0, 0, 0, 1), default, default, default, default);

        var objectType = m.AddTypeReference(runtime, m.GetOrAddString("System"), m.GetOrAddString("Object"));
        var exceptionType = m.AddTypeReference(runtime, m.GetOrAddString("System"), m.GetOrAddString("Exception"));
        var outer = m.AddTypeReference(satellite, m.GetOrAddString("Lib"), m.GetOrAddString("Outer"));
        m.AddTypeReference(outer, default(StringHandle), m.GetOrAddString("Inner"));
        var generic = m.AddTypeReference(satellite, m.GetOrAddString("Lib"), m.GetOrAddString("Generic`1"));
        var typeSpec = m.AddTypeSpecification(Sig(m, b => new BlobEncoder(b).TypeSpecificationSignature().GenericInstantiation(generic, 1, false).AddArgument().Int32()));

        var voidMethod = Sig(m, b => new BlobEncoder(b).MethodSignature(isInstanceMethod: false).Parameters(0, r => r.Void(), p => { }));
        var instanceVoid = Sig(m, b => new BlobEncoder(b).MethodSignature(isInstanceMethod: true).Parameters(0, r => r.Void(), p => { }));
        var genericMethod = Sig(m, b => new BlobEncoder(b).MethodSignature(SignatureCallingConvention.Default, 1, false).Parameters(0, r => r.Void(), p => { }));
        var makeRef = m.AddMemberReference(outer, m.GetOrAddString("Make"), voidMethod);
        var ctorRef = m.AddMemberReference(objectType, m.GetOrAddString(".ctor"), instanceVoid);
        var genericRef = m.AddMemberReference(outer, m.GetOrAddString("Convert"), genericMethod);
        var specRef = m.AddMethodSpecification(genericRef, Sig(m, b => new BlobEncoder(b).MethodSpecificationSignature(1).AddArgument().Int32()));
        var fieldRef = m.AddMemberReference(outer, m.GetOrAddString("Value"), Sig(m, b => new BlobEncoder(b).FieldSignature().Int32()));
        var locals = m.AddStandaloneSignature(Sig(m, b =>
        {
            var encoder = new BlobEncoder(b).LocalVariableSignature(3);
            encoder.AddVariable().Type().Int32();
            encoder.AddVariable().Type().Object();
            encoder.AddVariable().Type().String();
        }));
        var calli = m.AddStandaloneSignature(voidMethod);
        m.AddCustomAttribute(EntityHandle.AssemblyDefinition, ctorRef, m.GetOrAddBlob(new byte[] { 1, 0, 0, 0 }));
        int str = MetadataTokens.GetToken(m.GetOrAddUserString("synthetic é 中"));

        int T(EntityHandle handle) => MetadataTokens.GetToken(handle);
        var variants = new Dictionary<OperandType, int[]>
        {
            [OperandType.InlineMethod] = new[] { MethodDef, T(makeRef), T(specRef) },
            [OperandType.InlineField] = new[] { FieldDef, T(fieldRef) },
            [OperandType.InlineType] = new[] { T(objectType), TypeDef, T(typeSpec) },
            [OperandType.InlineTok] = new[] { T(objectType), TypeDef, FieldDef, MethodDef, T(typeSpec) },
            [OperandType.InlineString] = new[] { str },
            [OperandType.InlineSig] = new[] { T(calli) },
        };

        // Method 1: a tiny body.
        var tiny = new InstructionEncoder(new BlobBuilder());
        tiny.OpCode(ILOpCode.Ret);
        int tinyOffset = bodies.AddMethodBody(tiny, 1, default, MethodBodyAttributes.None);

        // Method 2: every opcode, each token operand with every token table it can name.
        var all = new InstructionEncoder(new BlobBuilder());
        var stream = all.CodeBuilder;
        var table = typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static).Select(x => x.GetValue(null)).OfType<OpCode>()
            .Where(x => !x.Name.StartsWith("prefix")).OrderBy(x => (ushort)x.Value).ToList();
        foreach (var op in table)
        {
            int[] tokens = variants.TryGetValue(op.OperandType, out var found) ? found : new[] { 0 };
            foreach (int token in tokens)
            {
                if ((ushort)op.Value > 0xFF) { stream.WriteByte((byte)(op.Value >> 8)); stream.WriteByte((byte)op.Value); } else stream.WriteByte((byte)op.Value);
                switch (op.OperandType)
                {
                    case OperandType.InlineNone: break;
                    case OperandType.ShortInlineBrTarget: stream.WriteSByte(0); break;
                    case OperandType.InlineBrTarget: stream.WriteInt32(0); break;
                    case OperandType.ShortInlineI: stream.WriteByte(op.Name == "ldc.i4.s" ? (byte)0xFD : (byte)1); break;
                    case OperandType.ShortInlineVar: stream.WriteByte(2); break;
                    case OperandType.InlineVar: stream.WriteUInt16(1); break;
                    case OperandType.InlineI: stream.WriteInt32(unchecked((int)0xA5555529)); break;
                    case OperandType.InlineI8: stream.WriteInt64(0x1122334455667788); break;
                    case OperandType.ShortInlineR: stream.WriteSingle(1.5f); break;
                    case OperandType.InlineR: stream.WriteDouble(-2.25); break;
                    case OperandType.InlineSwitch: stream.WriteInt32(3); stream.WriteInt32(0); stream.WriteInt32(0); stream.WriteInt32(0); break;
                    default: stream.WriteInt32(token); break;
                }
            }
        }
        int allOffset = bodies.AddMethodBody(all, 8, locals, MethodBodyAttributes.InitLocals);

        int small = Regions(bodies, m, exceptionType, 0);
        int fat = Regions(bodies, m, exceptionType, 300);

        var field = m.AddFieldDefinition(FieldAttributes.Public | FieldAttributes.Static, m.GetOrAddString("F"), Sig(m, b => new BlobEncoder(b).FieldSignature().Int32()));
        m.AddTypeDefinition(default, default, m.GetOrAddString("<Module>"), default, MetadataTokens.FieldDefinitionHandle(1), MetadataTokens.MethodDefinitionHandle(1));
        var attributes = MethodAttributes.Public | MethodAttributes.Static | MethodAttributes.HideBySig;
        var first = m.AddMethodDefinition(attributes, MethodImplAttributes.IL, m.GetOrAddString("Tiny"), voidMethod, tinyOffset, MetadataTokens.ParameterHandle(1));
        m.AddMethodDefinition(attributes, MethodImplAttributes.IL, m.GetOrAddString("AllOpcodes"), voidMethod, allOffset, MetadataTokens.ParameterHandle(1));
        m.AddMethodDefinition(attributes, MethodImplAttributes.IL, m.GetOrAddString("SmallRegions"), voidMethod, small, MetadataTokens.ParameterHandle(1));
        m.AddMethodDefinition(attributes, MethodImplAttributes.IL, m.GetOrAddString("FatRegions"), voidMethod, fat, MetadataTokens.ParameterHandle(1));
        m.AddTypeDefinition(TypeAttributes.Public | TypeAttributes.Abstract | TypeAttributes.Sealed | TypeAttributes.BeforeFieldInit, m.GetOrAddString("Synthetic"), m.GetOrAddString("Ops"), objectType, field, first);

        var peBuilder = new ManagedPEBuilder(PEHeaderBuilder.CreateLibraryHeader(), new MetadataRootBuilder(m), code, flags: CorFlags.ILOnly);
        var output = new BlobBuilder();
        peBuilder.Serialize(output);
        using var file = File.Create(path);
        output.WriteContentTo(file);
    }

    // catch, finally, fault and filter regions laid out one after another; `padding` nops widen the first try past the small-format limits.
    static int Regions(MethodBodyStreamEncoder bodies, MetadataBuilder m, TypeReferenceHandle exceptionType, int padding)
    {
        var flow = new ControlFlowBuilder();
        var e = new InstructionEncoder(new BlobBuilder(), flow);
        var done = e.DefineLabel();
        LabelHandle Mark() { var label = e.DefineLabel(); e.MarkLabel(label); return label; }

        var catchTry = Mark();
        for (int i = 0; i < padding; i++) e.OpCode(ILOpCode.Nop);
        e.Branch(ILOpCode.Leave, done);
        var catchHandler = Mark();
        e.OpCode(ILOpCode.Pop);
        e.Branch(ILOpCode.Leave, done);
        var catchEnd = Mark();
        flow.AddCatchRegion(catchTry, catchHandler, catchHandler, catchEnd, exceptionType);

        var finallyTry = Mark();
        e.OpCode(ILOpCode.Nop);
        e.Branch(ILOpCode.Leave, done);
        var finallyHandler = Mark();
        e.OpCode(ILOpCode.Endfinally);
        var finallyEnd = Mark();
        flow.AddFinallyRegion(finallyTry, finallyHandler, finallyHandler, finallyEnd);

        var faultTry = Mark();
        e.OpCode(ILOpCode.Nop);
        e.Branch(ILOpCode.Leave, done);
        var faultHandler = Mark();
        e.OpCode(ILOpCode.Endfinally);
        var faultEnd = Mark();
        flow.AddFaultRegion(faultTry, faultHandler, faultHandler, faultEnd);

        var filterTry = Mark();
        e.OpCode(ILOpCode.Nop);
        e.Branch(ILOpCode.Leave, done);
        var filterStart = Mark();
        e.OpCode(ILOpCode.Ldc_i4_1);
        e.OpCode(ILOpCode.Endfilter);
        var filterHandler = Mark();
        e.OpCode(ILOpCode.Pop);
        e.Branch(ILOpCode.Leave, done);
        var filterEnd = Mark();
        flow.AddFilterRegion(filterTry, filterStart, filterHandler, filterEnd, filterStart);

        e.MarkLabel(done);
        e.OpCode(ILOpCode.Ret);
        return bodies.AddMethodBody(e, 8, default, MethodBodyAttributes.None);
    }
}
