"""Semantic acceptance of the static .NET readers (managed.artifact, managed.members, managed.native_boundaries).

The expected values come from theseus_tests/fixtures/managed_oracle, a console app that reads the same bytes with the
runtime's own System.Reflection.Metadata. The assemblies are compiled here, by Roslyn (net8.0 SDK) and by the .NET
Framework csc, so no checked-in binary decides what is "correct".
"""
import copy
import hashlib
import json
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from test_native_formats import inspect

HERE = Path(__file__).parent
ORACLE_SOURCE = HERE / 'fixtures' / 'managed_oracle'
CSC = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')

COMMON = r'''
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading.Tasks;

[assembly: Gauge.Lab.Tag("assembly", 7, Note = "annot\u00e9 \u4e2d")]
[module: Gauge.Lab.Tag("module", 8)]
[assembly: TypeForwardedTo(typeof(System.Collections.Generic.Stack<>))]
[assembly: InternalsVisibleTo("@@FRIEND@@")]

public class GlobalType { public int Value; }

namespace Gauge.Lab
{
    [AttributeUsage(AttributeTargets.All, AllowMultiple = true)]
    public sealed class TagAttribute : Attribute
    {
        public string Name { get; private set; }
        public int Level { get; private set; }
        public string Note;
        public Type Kind { get; set; }
        public TagAttribute(string name, int level) { Name = name; Level = level; }
    }

    public enum Mode : byte { Off = 0, On = 1, Auto = 2 }
    [Flags] public enum Caps { None = 0, Read = 1, Write = 2, Both = Read | Write }
    public delegate int Reducer(int left, int right);
    public delegate TOut Mapper<in TIn, out TOut>(TIn value);

    public interface IMeter<out T> { T Read(); }
    public interface ISink : IDisposable
    {
        void Push<TItem>(TItem item) where TItem : class;
        event EventHandler Flushed;
        int Depth { get; }
        string this[int index] { get; set; }
    }

    [Tag("box", 3, Note = "n", Kind = typeof(Box<>))]
    public class Box<[Tag("tp", 1)] T> where T : class, IComparable<T>, new()
    {
        public const int Max = 42;
        public const string Label = "box";
        public static readonly int[] Table = new int[] { 1, 2, 3, 5, 8, 13, 21, 34 };
        public static int Counter;
        private T item;
        private Reducer reduced;
        public event EventHandler Changed;
        public event Reducer Reduced { add { reduced += value; } remove { reduced -= value; } }
        static Box() { Counter = Max + Table.Length; }
        public T Item
        {
            get { return item; }
            set { item = value; EventHandler h = Changed; if (h != null) h(this, EventArgs.Empty); }
        }
        public int Compare(T other) { return item == null ? 0 : item.CompareTo(other); }
        [Tag("convert", 2)]
        [return: Tag("ret", 3)]
        public TOut Convert<TIn, TOut>([Tag("param", 4)] TIn value) where TOut : struct { return default(TOut); }
        public int Use() { return Convert<int, double>(1) > 0 ? 1 : 0; }
        public T Make() { return new T(); }
        public Mapper<T, int> Map() { return delegate(T t) { return t == null ? 0 : 1; }; }
        public class Node { public Node Next; public T Value; public class Leaf { public int Depth; } }
        private struct Cell { public int A; public long B; }
        protected internal enum Level { Low, High }
    }

    public sealed class Meter : IMeter<double>, ISink
    {
        public bool Closed;
        public int depth;
        double IMeter<double>.Read() { return 1.5; }
        void IDisposable.Dispose() { Closed = true; }
        public void Push<TItem>(TItem item) where TItem : class { if (item != null) depth++; }
        public event EventHandler Flushed;
        public int Depth { get { return depth; } }
        public string this[int index] { get { return "slot" + index; } set { depth += index; } }
        public override string ToString() { return "meter"; }
        public static Meter operator +(Meter a, Meter b) { return new Meter { depth = a.depth + b.depth }; }
        public static implicit operator int(Meter m) { return m.depth; }
        public void Flush() { EventHandler h = Flushed; if (h != null) h(this, EventArgs.Empty); }
    }

    [StructLayout(LayoutKind.Explicit, Size = 16)]
    public struct Overlay
    {
        [FieldOffset(0)] public long Wide;
        [FieldOffset(0)] public int Low;
        [FieldOffset(4)] public int High;
    }

    [StructLayout(LayoutKind.Sequential, Pack = 2)]
    public struct Packed
    {
        public byte A;
        public int B;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 8)] public string C;
    }

    [Obsolete("legacy", false)]
    [Tag("flags", (int)Caps.Both)]
    [DebuggerDisplay("{Name}")]
    public class Tagged
    {
        [Tag("field", 1)] public int Slot;
        [Tag("property", 2)] public string Name { get; set; }
        [Tag("event", 3)] public event EventHandler Fired;
        public Mode Current = Mode.On;
        [Conditional("TRACE")] public static void Trace(string message) { }
        [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.Synchronized)] public int Sync() { return Slot; }
        public void Fire() { EventHandler h = Fired; if (h != null) h(this, EventArgs.Empty); }
    }

    public static class Calc
    {
        public static int Calls;
        public static string Name(int code)
        {
            switch (code)
            {
                case 0: return "zero";
                case 1: return "one";
                case 2: return "two";
                case 3: return "three";
                case 4: return "four";
                case 5: return "five";
                default: return "many";
            }
        }
        public static int Parse(string text)
        {
            switch (text)
            {
                case "alpha": return 1;
                case "beta": return 2;
                case "gamma": return 3;
                case "delta": return 4;
                case "epsilon": return 5;
                default: return 0;
            }
        }
        public static int Fold(int[] data, Reducer reduce) { int acc = 0; foreach (int v in data) acc = reduce(acc, v); return acc; }
        public static Func<int, int> Closure(int factor) { int total = 0; return delegate(int x) { total += x * factor; return total; }; }
        public static int Lambdas(IEnumerable<int> source)
        {
            int sum = 0;
            Func<int, bool> even = x => x % 2 == 0;
            Action<int> add = x => sum += x;
            foreach (int v in source) if (even(v)) add(v);
            return sum;
        }
        public static async Task<int> RunAsync(int delay)
        {
            try { await Task.Delay(delay); return delay; }
            catch (InvalidOperationException) { return -1; }
            finally { Calls++; }
        }
        public static IEnumerable<int> Count(int n) { for (int i = 0; i < n; i++) yield return i * i; }
        public static int Locked(object gate, int[] values)
        {
            lock (gate) { int s = 0; for (int i = 0; i < values.Length; i++) s += values[i]; return s; }
        }
        public static int Disposing(IDisposable d) { using (d) { return d == null ? 0 : 1; } }
        public static int Grid() { int[,] grid = new int[3, 4]; grid[1, 2] = 5; return grid[1, 2] + grid.GetLength(0); }
        public static int Generics()
        {
            var list = new List<string>(); list.Add("x");
            var map = new Dictionary<string, List<int>>(); map["a"] = new List<int>();
            return list.Count + map.Count;
        }
        public static object Boxing(int v, object o) { string s = o as string; if (o is int) return (int)o + v; return s ?? (object)v; }
        public static int Checked(int a, int b) { return checked(a * b); }
        public static int Mix(ref int a, out int b, int c = 5, params int[] rest) { b = a + c; a = rest.Length; return a; }
        public static Type Tokens() { return typeof(Box<>).MakeGenericType(typeof(string)); }
        public static int Size() { return Marshal.SizeOf(typeof(Overlay)); }
        public static string Unicode() { return "caf\u00e9 \u4e2d\u6587 \u0001 plain"; }
        public static string Latin1() { return "café"; }
        public static int Big(int n)
        {
            int acc = n;
            try
            {
                if (n > 0)
                {
@@REPEAT@@
                }
            }
            catch (Exception) { acc = -1; }
            return acc;
        }
    }

    public static class Native
    {
        [DllImport("kernel32.dll", EntryPoint = "GetTickCount64", ExactSpelling = true)]
        public static extern ulong Tick();
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "GetModuleHandleW")]
        public static extern IntPtr Module([MarshalAs(UnmanagedType.LPWStr)] string name);
        [DllImport("user32.dll", CharSet = CharSet.Ansi, CallingConvention = CallingConvention.StdCall, BestFitMapping = false, ThrowOnUnmappableChar = true, EntryPoint = "MessageBoxA")]
        public static extern int Box(IntPtr owner, string text, string caption, uint type);
        [DllImport("msvcrt.dll", CallingConvention = CallingConvention.Cdecl, CharSet = CharSet.Auto)]
        public static extern int abs(int value);
        [DllImport("kernel32", PreserveSig = false, BestFitMapping = true)]
        public static extern void Sleep(uint milliseconds);
        [DllImport("user32.dll", CallingConvention = CallingConvention.ThisCall)]
        public static extern int Wrapper(IntPtr self);
        [DllImport("user32.dll", CallingConvention = CallingConvention.FastCall, ThrowOnUnmappableChar = false)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool Fast(int value);
        public static int Call() { return (int)Tick() + abs(-1); }
    }
}
'''.replace('@@REPEAT@@', '                    acc = acc * 31 + n;\n' * 90)

MODERN = r'''
#nullable enable
using System;
using System.Collections.Generic;
using System.Threading.Tasks;

namespace Gauge.Modern;

public record Reading(string Sensor, double Value) { public int Tick { get; init; } }
public readonly record struct Point(int X, int Y);
public interface IShape { static abstract int Sides { get; } int Area() => 0; }
public struct Square : IShape { public static int Sides => 4; public int Area() => 9; }
public ref struct Window { public Span<byte> Bytes; public Window(Span<byte> bytes) { Bytes = bytes; } public int Length => Bytes.Length; }
public class Required { public required string Id { get; init; } public string? Note { get; set; } }

public static unsafe class Pointers
{
    public static int Call(delegate*<int, int> f, int v) => f(v);
    public static delegate*<int, int> Make() => &Twice;
    static int Twice(int x) => x * 2;
    public static int First(int[] a) { fixed (int* p = a) return *p; }
    public static int Stack() { Span<int> s = stackalloc int[4]; s[1] = 3; return s[1]; }
    public static T Read<T>(T* p) where T : unmanaged => *p;
}

public static class Modern
{
    public static int Try(object o)
    {
        try { return o.GetHashCode(); }
        catch (InvalidOperationException e) when (e.Message.Length > 3) { return 1; }
    }
    public static string Fmt(int a) => $"v={a} {a:x}";
    public static string Arms(int code) => code switch { 0 => "zero", 1 => "one", 2 => "two", 3 => "three", 4 => "four", 5 => "five", _ => "many" };
    public static async ValueTask<int> Wait(int ms) { await Task.Delay(ms); return ms; }
    public static async IAsyncEnumerable<int> Stream(int n) { for (int i = 0; i < n; i++) { await Task.Yield(); yield return i; } }
    public static int Local(int n) { int Twice(int v) => v * 2; Func<int, int> f = static v => v + 1; return Twice(n) + f(n); }
    public static int Using() { using var d = new System.IO.MemoryStream(); return (int)d.Length; }
    public static int Pattern(object o) => o is int i && i > 3 ? i : o is string { Length: > 2 } s ? s.Length : 0;
}
'''

FRAMEWORK_ATTRIBUTE = '[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]\n'
ENTRY = 'public static class Entry { [STAThread] public static int Main(string[] args) { return Gauge.Lab.Calc.Name(args.Length).Length; } }\n'
PAYLOAD = b'resource payload \xc3\xa9\r\n' * 7
BLOB = bytes(range(256)) * 3
LINKED = b'linked resource body'


def public_snk():
    """A delay-sign public key blob (sn -p layout) with a deterministic 1024-bit modulus."""
    modulus = bytearray(b''.join(hashlib.sha256(bytes([i])).digest() for i in range(4)))
    modulus[0] |= 1
    modulus[-1] |= 0x80
    blob = bytes([6, 2, 0, 0, 0, 0x24, 0, 0]) + b'RSA1' + (1024).to_bytes(4, 'little') + (65537).to_bytes(4, 'little') + bytes(modulus)
    return (0x2400).to_bytes(4, 'little') + (0x8004).to_bytes(4, 'little') + len(blob).to_bytes(4, 'little') + blob


def prepare(source, delay_sign, framework):
    friend = 'Gauge.Lab.Friend' + (', PublicKey=' + public_snk().hex() if delay_sign else '')
    source = source.replace('@@FRIEND@@', friend)
    marker = '[assembly: Gauge.Lab.Tag'
    return source.replace(marker, FRAMEWORK_ATTRIBUTE + marker, 1) if framework else '#nullable disable\n' + source


def tool_env(root):
    env = dict(os.environ, NUGET_PACKAGES=str(root / 'nuget'), DOTNET_CLI_HOME=str(root / 'home'), DOTNET_NOLOGO='1',
               DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', MSBUILDDISABLENODEREUSE='1',
               DOTNET_ROLL_FORWARD='', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='')
    for name in ['DOTNET_ROOT', 'DOTNET_ROOT(x86)', 'MSBUILD_EXE_PATH', 'MSBuildSDKsPath', 'MSBuildExtensionsPath']:
        env.pop(name, None)
    return env


def run(command, cwd, env=None):
    done = subprocess.run([str(part) for part in command], cwd=cwd, env=env, capture_output=True, timeout=300)
    text = (done.stdout + done.stderr).decode('utf8', 'replace')
    assert done.returncode == 0, ' '.join(str(part) for part in command[:3]) + '\n' + text[-3000:]
    return text


def find_dotnet():
    dotnet = shutil.which('dotnet') or 'C:/Program Files/dotnet/dotnet.exe'
    if not Path(dotnet).is_file():
        pytest.skip('dotnet SDK not installed')
    sdks = subprocess.run([dotnet, '--list-sdks'], capture_output=True, text=True).stdout
    if not any(line.startswith('8.0.') for line in sdks.splitlines()):
        pytest.skip('A .NET 8 SDK is required')
    return dotnet


def sdk_build(dotnet, env, root, name, sources, config, platform, debug_type, delay_sign):
    project = root / name
    project.mkdir()
    (project / 'global.json').write_text('{"sdk":{"version":"8.0.100","rollForward":"latestFeature"}}')
    (project / 'Common.cs').write_text(prepare(sources['common'], delay_sign, False), encoding='utf8')
    (project / 'Modern.cs').write_text(sources['modern'], encoding='utf8')
    (project / 'payload.txt').write_bytes(PAYLOAD)
    (project / 'blob.bin').write_bytes(BLOB)
    (project / 'lab.snk').write_bytes(public_snk())
    signing = '<SignAssembly>true</SignAssembly><DelaySign>true</DelaySign><AssemblyOriginatorKeyFile>lab.snk</AssemblyOriginatorKeyFile>' if delay_sign else ''
    (project / 'GaugeLab.csproj').write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework><OutputType>Library</OutputType><LangVersion>12.0</LangVersion>
    <Nullable>enable</Nullable><ImplicitUsings>disable</ImplicitUsings><AllowUnsafeBlocks>true</AllowUnsafeBlocks>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems><Deterministic>true</Deterministic>
    <PlatformTarget>{platform}</PlatformTarget><DebugType>{debug_type}</DebugType><Optimize>{'true' if config == 'Release' else 'false'}</Optimize>
    <NoWarn>CS0169;CS0649;CS0414;CS0067;CS8618;CS8625;CS1591;CS0618;CS8981</NoWarn>{signing}
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="Common.cs" /><Compile Include="Modern.cs" />
    <EmbeddedResource Include="payload.txt" LogicalName="payload.txt" />
    <EmbeddedResource Include="blob.bin" LogicalName="Gauge.Blob" />
  </ItemGroup>
</Project>''')
    run([dotnet, 'build', 'GaugeLab.csproj', '-c', config, '-o', project / 'out', '--disable-build-servers', '-nologo', '-v', 'q'], project, env)
    return project / 'out' / 'GaugeLab.dll'


def csc_build(root, name, source, target, platform, optimize, debug, delay_sign):
    work = root / name
    work.mkdir()
    (work / 'lab.cs').write_text(prepare(source, delay_sign, True), encoding='utf8')
    (work / 'payload.txt').write_bytes(PAYLOAD)
    (work / 'blob.bin').write_bytes(BLOB)
    (work / 'linked.bin').write_bytes(LINKED)
    (work / 'lab.snk').write_bytes(public_snk())
    out = work / ('lab.dll' if target == 'library' else 'lab.exe')
    command = [CSC, '/nologo', '/target:' + target, '/platform:' + platform, '/optimize' + ('+' if optimize else '-'), '/debug' + ('+' if debug else '-'),
               '/codepage:65001', '/resource:payload.txt,payload.txt', '/resource:blob.bin,Gauge.Blob,private', '/linkresource:linked.bin,linked.bin',
               '/nowarn:0169,0649,0414,0067,0618', '/out:' + str(out)]
    if delay_sign:
        command += ['/keyfile:lab.snk', '/delaysign+']
    run(command + ['lab.cs'], work)
    return out


VARIANTS = ['net8-anycpu', 'net8-x64-debug-signed', 'fw-anycpu', 'fw-pref32-exe-signed', 'fw-x86-unoptimised', 'synthetic-opcodes']
OPERATIONS = ['managed.artifact', 'managed.members', 'managed.native_boundaries']


class Lab:
    """Builds the oracle and the test assemblies on demand and caches oracle and product documents per assembly."""

    def __init__(self, root):
        self.root = root
        self.dotnet = find_dotnet()
        if not CSC.is_file():
            pytest.skip('The .NET Framework C# compiler is required')
        self.env = tool_env(root)
        self.dlls, self.oracles, self.products = {}, {}, {}
        project = root / 'oracle-build'
        shutil.copytree(ORACLE_SOURCE, project)
        (project / 'global.json').write_text('{"sdk":{"version":"8.0.100","rollForward":"latestFeature"}}')
        run([self.dotnet, 'build', 'ManagedOracle.csproj', '-c', 'Release', '-o', project / 'out', '--disable-build-servers', '-nologo', '-v', 'q'], project, self.env)
        self.oracle_dll = project / 'out' / 'ManagedOracle.dll'

    def assembly(self, name):
        if name not in self.dlls:
            sources = {'common': COMMON, 'modern': MODERN}
            if name == 'synthetic-opcodes':
                self.dlls[name] = self.root / 'synthetic.dll'
                run([self.dotnet, self.oracle_dll, '--emit', self.dlls[name]], self.root, self.env)
                return self.dlls[name]
            self.dlls[name] = {
                'net8-anycpu': lambda: sdk_build(self.dotnet, self.env, self.root, name, sources, 'Release', 'AnyCPU', 'none', False),
                'net8-x64-debug-signed': lambda: sdk_build(self.dotnet, self.env, self.root, name, sources, 'Debug', 'x64', 'embedded', True),
                'fw-anycpu': lambda: csc_build(self.root, name, COMMON, 'library', 'anycpu', True, False, False),
                'fw-pref32-exe-signed': lambda: csc_build(self.root, name, COMMON + ENTRY, 'exe', 'anycpu32bitpreferred', True, False, True),
                'fw-x86-unoptimised': lambda: csc_build(self.root, name, COMMON, 'library', 'x86', False, True, False),
            }[name]()
        return self.dlls[name]

    def oracle(self, name):
        if name not in self.oracles:
            target = self.root / (name + '.oracle.json')
            run([self.dotnet, self.oracle_dll, self.assembly(name), target], self.root, self.env)
            self.oracles[name] = json.loads(target.read_text(encoding='utf8'))
        return self.oracles[name]

    def product(self, name, operation, parameters=None, expected_state='finished'):
        key = (name, operation, json.dumps(parameters, sort_keys=True), expected_state)
        if key not in self.products:
            folder = self.root / ('%s-%s-%d' % (name, operation, len(self.products)))
            folder.mkdir()
            self.products[key] = inspect(folder, operation, self.assembly(name).read_bytes(), parameters, expected_state)
        return self.products[key]


@pytest.fixture(scope='session')
def lab(tmp_path_factory):
    return Lab(tmp_path_factory.mktemp('managed-oracle'))


@pytest.fixture(params=VARIANTS)
def name(request):
    return request.param


@pytest.fixture
def oracle(lab, name):
    return lab.oracle(name)


@pytest.fixture
def artifact(lab, name):
    return lab.product(name, 'managed.artifact')


@pytest.fixture
def members(lab, name):
    return lab.product(name, 'managed.members')


@pytest.fixture
def native(lab, name):
    return lab.product(name, 'managed.native_boundaries')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def by_token(rows, key='token'):
    table = {row[key]: row for row in rows}
    assert len(table) == len(rows), 'duplicate ' + key
    return table


def lower_keys(counts):
    # The product spells FieldRVA / EncLog where System.Reflection.Metadata spells FieldRva / EncLog; compare case-insensitively.
    return {key.lower(): value for key, value in counts.items()}


def qualified(row):
    # A TypeDef/TypeRef row is named by its own namespace and name; enclosing types are carried by the NestedClass link, not the string.
    return row['namespace'] + '.' + row['name'] if row['namespace'] else row['name']


def type_names(oracle):
    names = {row['token']: qualified(row) for row in oracle['type_defs'] + oracle['type_refs']}
    return names


def name_digest(oracle, token):
    """The documented nominal digest: 0x00 || ns || 0x00 || name, nested as 0x01 || outer digest || ns || 0x00 || name."""
    rows = {row['token']: row for row in oracle['type_defs']}
    row = rows[token]
    prefix = b'\x00' if row['enclosing'] is None else b'\x01' + bytes.fromhex(name_digest(oracle, row['enclosing']))
    return sha(prefix + row['namespace'].encode() + b'\x00' + row['name'].encode())


def float_equal(left, right):
    try:
        return float(left) == float(right) or (float(left) != float(left) and float(right) != float(right))
    except ValueError:
        return False


ARCHITECTURE = {0x14c: 'x86', 0x8664: 'x86_64', 0x1c4: 'arm', 0xaa64: 'arm64'}
OPTIONAL_HEADER = {0x10b: 'pe32', 0x20b: 'pe32-plus'}
CLI_FLAG_NAMES = [(0x1, 'il-only'), (0x2, '32-bit-required'), (0x8, 'strong-name-signed'), (0x10, 'native-entry-point'),
                  (0x10000, 'track-debug-data'), (0x20000, '32-bit-preferred')]
REQUIRED_TABLES = {'typedef', 'nestedclass', 'genericparam', 'genericparamconstraint', 'methodimpl', 'event', 'eventmap', 'property',
                   'propertymap', 'methodsemantics', 'implmap', 'moduleref', 'classlayout', 'fieldlayout', 'fieldmarshal', 'fieldrva',
                   'constant', 'manifestresource', 'exportedtype', 'methodspec', 'typespec', 'memberref', 'customattribute',
                   'interfaceimpl', 'standalonesig', 'assemblyref', 'param', 'typeref', 'file'}


def all_instructions(oracle):
    return [(method['token'], row) for method in oracle['methods'] if method['body'] for row in method['body']['instructions']]


# --- the oracle itself -------------------------------------------------------------------------------------------------

def test_oracle_opcode_table_agrees_with_ilopcode(lab):
    assert lab.oracle(VARIANTS[0])['opcode_table_mismatches'] == []


def test_oracle_resource_bytes_are_the_bytes_that_were_embedded(oracle, name):
    if name == 'synthetic-opcodes':
        pytest.skip('no resources')
    data = {row['name']: row for row in oracle['resources']}
    assert data['payload.txt']['data_sha256'] == sha(PAYLOAD) and data['payload.txt']['data_length'] == len(PAYLOAD)
    assert data['Gauge.Blob']['data_sha256'] == sha(BLOB) and data['Gauge.Blob']['data_length'] == len(BLOB)


def test_fixture_exercises_the_constructs_under_test(oracle, name):
    bodies = [method['body'] for method in oracle['methods'] if method['body']]
    opcodes = Counter(row['opcode'] for _, row in all_instructions(oracle))
    if name == 'synthetic-opcodes':
        assert set(opcodes) == set(oracle['opcode_names']), sorted(set(oracle['opcode_names']) - set(opcodes))
        assert {region['kind'] for body in bodies for region in body['exception_regions']} == {0, 1, 2, 4}
        assert {body['eh_format'] for body in bodies if body['eh_format']} == {'small', 'fat'}
        assert {row['kind'] for row in oracle['member_refs']} == {'Method', 'Field'} and len(oracle['method_specs']) == 1 and len(oracle['type_specs']) == 1
        assert [row['culture'] for row in oracle['assembly_refs']] == [None, 'en-US', None]
        assert [row['flags'] for row in oracle['assembly_refs']] == [0, 0x101, 0]
        assert [row['public_key_or_token']['kind'] for row in oracle['assembly_refs']] == ['public-key-token', 'public-key', 'none']
        assert oracle['assembly']['culture'] == 'fr-FR' and oracle['assembly']['version'] == '9.8.7.6'
        return
    tables = {key.lower() for key in oracle['table_row_counts']}
    assert REQUIRED_TABLES - tables == (set() if name.startswith('fw') else {'file'})
    for required in ['switch', 'ldfld', 'stfld', 'ldsfld', 'stsfld', 'ldflda', 'call', 'callvirt', 'newobj', 'ldftn', 'ldtoken', 'ldstr', 'leave', 'endfinally', 'brfalse', 'br.s', 'constrained.', 'isinst', 'box', 'unbox.any']:
        assert opcodes[required] or opcodes[required + '.s'], required
    assert any(opcode in opcodes for opcode in ['br', 'brtrue', 'brfalse', 'ble', 'blt', 'leave']), 'a long-form branch'
    assert {body['header_format'] for body in bodies} == {'tiny', 'fat'}
    kinds = {region['kind'] for body in bodies for region in body['exception_regions']}
    assert {0, 2} <= kinds and (1 in kinds) == name.startswith('net8')
    assert {'small', 'fat'} <= {body['eh_format'] for body in bodies if body['eh_format']}, 'both exception table formats'
    assert {int(row['parent'], 16) >> 24 for row in oracle['custom_attributes']} >= {0x00, 0x02, 0x04, 0x06, 0x08, 0x14, 0x17, 0x20, 0x2a}
    assert len(oracle['exported_types']) == 2 and len(oracle['module_refs']) == 4 and len(oracle['resources']) == (2 if name.startswith('net8') else 3)
    assert sum(1 for method in oracle['methods'] if method['import']) == 7
    assert {method['import']['attributes'] & 0x700 for method in oracle['methods'] if method['import']} >= {0x100, 0x200, 0x300, 0x400, 0x500}
    assert len(oracle['fields']) > 30 and len(oracle['methods']) > 90 and len(oracle['member_refs']) > 80 and len(oracle['custom_attributes']) > 40
    assert sum(1 for row in oracle['type_defs'] if row['enclosing']) >= 8 and len(oracle['generic_params']) > 5
    flags = oracle['cli']['flags']
    assert (flags & 0x20000 != 0) == (name == 'fw-pref32-exe-signed') and (oracle['assembly']['public_key']['kind'] == 'public-key') == ('signed' in name)


# --- managed.artifact --------------------------------------------------------------------------------------------------

def test_pe_and_cli_header_match_the_runtime_reader(artifact, oracle):
    pe, cli, want, headers = artifact['pe'], artifact['pe']['cli'], oracle['cli'], oracle['pe']
    assert (pe['machine'], pe['architecture'], pe['optional_header'], pe['section_count'], pe['characteristics']) == (
        headers['machine'], ARCHITECTURE[headers['machine']], OPTIONAL_HEADER[headers['magic']], headers['section_count'], headers['characteristics'])
    assert (cli['header_offset'], cli['runtime_version'], cli['flags']) == (want['header_offset'], want['runtime_version'], want['flags'])
    assert cli['flag_names'] == [label for bit, label in CLI_FLAG_NAMES if want['flags'] & bit]
    for product_key, source in [('metadata', 'metadata'), ('resources', 'resources'), ('strong_name', 'strong_name'), ('managed_native_header', 'managed_native_header')]:
        assert (cli[product_key + '_rva'], cli[product_key + '_size']) == (want[source]['rva'], want[source]['size']), product_key
    entry = want['entry_point']
    expected = {'kind': 'none', 'value': None} if entry == 0 else {'kind': 'native-rva', 'value': entry} if want['flags'] & 0x10 else {'kind': 'metadata-token', 'value': '0x%08x' % entry}
    assert cli['entry_point'] == expected
    assert cli['ready_to_run_signature'] is False


def test_classification_follows_machine_cli_flags_and_target_framework(artifact, oracle):
    flags, machine = oracle['cli']['flags'], oracle['pe']['machine']
    # CorFlags 32BITREQUIRED together with 32BITPREFERRED is "AnyCPU, prefer 32-bit", not a 32-bit requirement.
    architecture = ARCHITECTURE[machine] if machine != 0x14c else 'anycpu-prefer-32' if flags & 0x20000 else 'x86' if flags & 0x2 else 'anycpu'
    classification = artifact['classification']
    assert (classification['status'], classification['container'], classification['implementation']) == ('managed', 'pe', 'cil')
    assert classification['managed_architecture'] == architecture
    frameworks = oracle['target_frameworks']
    assert classification['runtime_family'] == ('unknown' if not frameworks else 'modern-dotnet' if frameworks[0].startswith('.NETCoreApp') else 'dotnet-framework')
    assert artifact['target_frameworks'] == oracle['target_frameworks']


def test_metadata_version_table_row_counts_and_coverage(artifact, members, native, oracle):
    for document in (artifact, members, native):
        assert document['metadata']['version'] == oracle['metadata_version']
        assert lower_keys(document['metadata']['table_row_counts']) == lower_keys(oracle['table_row_counts'])
    assert artifact['coverage'] == native['coverage'] == {'state': 'complete', 'issues': []}
    assert artifact['metadata']['status'] == native['metadata']['status'] == 'complete'


def test_module_identity_is_identical_in_all_three_documents(artifact, members, native, oracle):
    want = oracle['module']
    for document in (artifact, members, native):
        module = document['module']
        assert (module['name'], module['mvid'], module['generation'], module['enc_id'], module['enc_base_id'], module['token']) == (
            want['name'], want['mvid'], want['generation'], want['enc_id'], want['enc_base_id'], '0x00000001')
    for document in (members, native):
        assert document['identity_scope'] == {'token_identity': 'build-local', 'requires_artifact_sha256': document['artifact']['sha256'], 'requires_mvid': want['mvid']}


def test_assembly_identity_including_public_key_and_token(artifact, oracle):
    want, got = oracle['assembly'], artifact['assembly']
    assert {key: got[key] for key in ['name', 'version', 'culture', 'flags', 'hash_algorithm', 'public_key']} == {key: want[key] for key in ['name', 'version', 'culture', 'flags', 'hash_algorithm', 'public_key']}
    assert got['token'] == '0x20000001'
    if want['public_key']['kind'] == 'public-key':
        assert want['flags'] & 1 and want['public_key']['byte_length'] == 160 and want['public_key']['sha256'] == sha(public_snk())


def test_assembly_references(artifact, oracle):
    want, got = by_token(oracle['assembly_refs']), by_token(artifact['references'])
    assert set(got) == set(want) and want
    for token, row in got.items():
        expected = want[token]
        for key in ['name', 'version', 'culture', 'flags', 'public_key_or_token', 'hash_value_length', 'hash_value_sha256']:
            assert row[key] == expected[key], (token, key)


def test_custom_attribute_parents_constructors_and_value_hashes(artifact, oracle):
    got = sorted((row['token'], row['parent_token'], row['constructor_token'], row['type_name'], row['value_length'], row['value_sha256']) for row in artifact['attributes'])
    want = sorted((row['token'], row['parent'], row['constructor'], row['type_name'], row['value_length'], row['value_sha256']) for row in oracle['custom_attributes'])
    assert got == want and want


def test_manifest_resources_including_linked_and_private(artifact, oracle):
    want, got = by_token(oracle['resources']), by_token(artifact['resources'])
    assert set(got) == set(want)
    for token, row in got.items():
        expected = want[token]
        assert (row['name'], row['flags'], row['implementation_token'], row['embedded'], row['declared_offset'], row['data_length'], row['data_sha256']) == (
            expected['name'], expected['flags'], expected['implementation'], expected['embedded'], expected['offset'], expected['data_length'], expected['data_sha256']), token
        assert row['visibility'] == {1: 'public', 2: 'private'}[expected['flags'] & 7]


# --- managed.members ---------------------------------------------------------------------------------------------------

def test_type_rows_nesting_member_lists_and_name_digests(members, oracle):
    want, got = by_token(oracle['type_defs']), by_token(members['types'])
    assert set(got) == set(want) and members['nesting_read'] is True
    for token, row in got.items():
        expected = want[token]
        assert (row['namespace'], row['name'], row['flags'], row['extends_token'], row['enclosing_type_token']) == (
            expected['namespace'], expected['name'], expected['flags'], expected['extends'], expected['enclosing']), token
        assert row['full_name'] == qualified(expected)
        assert row['name_sha256'] == name_digest(oracle, token), token
        for member, rows in (('field_list', expected['field_rows']), ('method_list', expected['method_rows'])):
            assert row[member] == {'first_row': rows[0] if rows else None, 'last_row': rows[-1] if rows else None, 'count': len(rows)}, (token, member)


def check_signature(row, wanted):
    blob = bytes.fromhex(wanted['signature'])
    signature, decoded = row['signature'], wanted['decoded']
    assert (signature['raw_length'], signature['raw_sha256']) == (len(blob), sha(blob))
    assert (signature['kind'], signature['parse_status'], signature['issue'], signature['calling_convention']) == (decoded['kind'], 'decoded', None, decoded['convention'])
    if decoded['kind'] == 'field':
        assert signature['field_type'] == decoded['field_type']
    else:
        assert (signature['parameter_count'], signature['generic_parameter_count'], signature['return_type'], signature['parameter_types']) == (
            decoded['parameter_count'], decoded['generic_parameter_count'], decoded['return_type'], decoded['parameter_types'])


def test_field_tokens_names_flags_and_signatures(members, oracle):
    want, got = by_token(oracle['fields']), by_token(members['fields'])
    assert set(got) == set(want) and want
    types = by_token(oracle['type_defs'])
    for token, row in got.items():
        expected = want[token]
        assert (row['declaring_type_token'], row['name'], row['flags']) == (expected['declaring_type'], expected['name'], expected['flags']), token
        assert row['declaring_type'] == qualified(types[expected['declaring_type']])
        check_signature(row, expected)


def test_method_tokens_names_flags_rva_and_signatures(members, oracle):
    want, got = by_token(oracle['methods']), by_token(members['methods'])
    assert set(got) == set(want) and want
    types = by_token(oracle['type_defs'])
    for token, row in got.items():
        expected = want[token]
        assert (row['declaring_type_token'], row['name'], row['rva'], row['flags'], row['impl_flags']) == (
            expected['declaring_type'], expected['name'], expected['rva'], expected['flags'], expected['impl_flags']), token
        assert row['declaring_type'] == qualified(types[expected['declaring_type']])
        check_signature(row, expected)


def test_method_bodies_header_il_size_max_stack_locals_and_regions(members, oracle):
    want, got = by_token(oracle['methods']), by_token(members['methods'])
    for token, row in got.items():
        expected, body = want[token]['body'], row['body']
        if expected is None:
            assert body['status'] == 'absent' and body['il_size'] == 0 and body['instructions'] == [], token
            continue
        assert body['status'] == 'present' and body['issue'] is None and body['rva'] == want[token]['rva'], token
        assert (body['header_format'], body['max_stack'], body['init_locals'], body['local_var_sig_token'], body['il_size'], body['il_sha256']) == (
            expected['header_format'], expected['max_stack'], expected['init_locals'], expected['local_signature'], expected['il_size'], expected['il_sha256']), token
        assert (body['instruction_count'], body['decoded_instruction_count'], body['truncated_instructions']) == (expected['instruction_count'], expected['instruction_count'], 0), token
        assert body['opcode_counts'] == expected['opcode_counts'], token
        regions = [(r['flags'], r['try_offset'], r['try_length'], r['handler_offset'], r['handler_length'], r['class_token'], r['filter_offset']) for r in body['exception_regions']]
        assert regions == [(r['kind'], r['try_offset'], r['try_length'], r['handler_offset'], r['handler_length'], r['catch_type'], None if r['filter_offset'] < 0 else r['filter_offset']) for r in expected['exception_regions']], token


def test_every_decoded_instruction_matches_offsets_opcodes_operands_and_bytes(members, oracle):
    got = by_token(members['methods'])
    checked = 0
    for method in oracle['methods']:
        if not method['body']:
            continue
        product = got[method['token']]['body']['instructions']
        assert len(product) == len(method['body']['instructions']), method['token']
        for mine, theirs in zip(product, method['body']['instructions']):
            assert (mine['il_offset'], mine['opcode'], mine['bytes']) == (theirs['il_offset'], theirs['opcode'], theirs['bytes']), method['token']
            if theirs['opcode'] in ('ldc.r4', 'ldc.r8'):
                assert float_equal(mine['operand'], theirs['operand']), (method['token'], theirs)
            else:
                assert mine['operand'] == theirs['operand'], (method['token'], theirs)
            checked += 1
    assert checked > 200


def test_member_refs_parents_names_and_signatures(members, oracle):
    want, got = by_token(oracle['member_refs']), by_token(members['member_refs'])
    assert set(got) == set(want) and want
    names = type_names(oracle)
    for token, row in got.items():
        expected = want[token]
        assert (row['parent_token'], row['name']) == (expected['parent'], expected['name']), token
        assert row['parent_name'] == parent_name(names, expected), token
        check_signature(row, expected)


def parent_name(names, member_ref):
    """TypeDef/TypeRef parents by row name; a TypeSpec parent by the generic type it instantiates; anything else has no name."""
    return names.get(member_ref['parent']) or names.get(member_ref['parent_generic_type'])


def target_facts(oracle):
    """token -> (kind, name, declaring type name), resolved only from rows the oracle read."""
    types, refs = by_token(oracle['type_defs']), by_token(oracle['member_refs'])
    names = type_names(oracle)
    methods, fields = by_token(oracle['methods']), by_token(oracle['fields'])
    facts = {}
    for token, row in methods.items():
        facts[token] = ('method-def', row['name'], qualified(types[row['declaring_type']]))
    for token, row in fields.items():
        facts[token] = ('field-def', row['name'], qualified(types[row['declaring_type']]))
    for token, row in refs.items():
        facts[token] = ('member-ref', row['name'], parent_name(names, row))
    for row in oracle['method_specs']:
        facts[row['token']] = ('method-spec',) + facts[row['method']][1:]
    return facts


def test_call_edges_equal_the_il_call_sites_of_every_method(members, oracle):
    facts = target_facts(oracle)
    want = {method['token']: Counter((site['opcode'], site['token']) for site in method['body']['call_sites']) for method in oracle['methods'] if method['body']}
    got = {}
    for edge in members['call_edges']:
        got.setdefault(edge['caller_token'], Counter())[edge['opcode'], edge['target_token']] += 1
    assert {token: set(counts) for token, counts in got.items()} == {token: set(counts) for token, counts in want.items() if counts}
    assert got == {token: counts for token, counts in want.items() if counts}
    for edge in members['call_edges']:
        kind, name, declaring = facts[edge['target_token']]
        assert (edge['target_kind'], edge['target_name'], edge['target_declaring_type']) == (kind, name, declaring), edge


def test_field_accesses_equal_the_il_field_sites_of_every_method(members, oracle):
    facts = target_facts(oracle)
    want = {method['token']: Counter((site['opcode'], site['token']) for site in method['body']['field_sites']) for method in oracle['methods'] if method['body']}
    got = {}
    for access in members['field_accesses']:
        got.setdefault(access['method_token'], Counter())[access['opcode'], access['field_token']] += 1
    assert got == {token: counts for token, counts in want.items() if counts}
    for access in members['field_accesses']:
        _, name, declaring = facts[access['field_token']]
        assert (access['field_name'], access['field_declaring_type']) == (name, declaring), access


def test_exported_types_forwarders_and_nested_forwarders(members, oracle):
    want, got = by_token(oracle['exported_types']), by_token(members['exported_types'])
    assert set(got) == set(want)
    for token, row in got.items():
        expected = want[token]
        assert (row['namespace'], row['name'], row['flags'], row['type_def_id'], row['implementation_token'], row['forwarder']) == (
            expected['namespace'], expected['name'], expected['flags'], expected['type_def_id'], expected['implementation'], bool(expected['flags'] & 0x200000)), token


def compiler_flag(row):
    # Roslyn and the .NET Framework compiler write 1 where the only trigger is a unit in 0x80-0xFF; the spec text gives 0.
    return row['ecma_terminal'] == 0 and row['terminal_byte'] == 1 and any(0x80 <= ord(char) <= 0xff for char in row['value'])


def flag_disagrees(row):
    return row['terminal_byte'] != row['ecma_terminal'] and not compiler_flag(row)


def test_user_string_literals_and_their_terminal_flag_diagnostics(members, oracle):
    referenced = {row['token']: row for row in oracle['user_strings'] if row['referenced_by_ldstr']}
    literals = members['user_strings']['literals']
    assert {row['token']: row['value'] for row in literals} == {token: row['value'] for token, row in referenced.items()} and literals
    expected_issues = {'metadata.#US:' + token for token, row in referenced.items() if flag_disagrees(row)}
    issues = members['user_strings']['issues']
    assert {issue['scope'] for issue in issues} == expected_issues
    assert all(issue['code'] == 'invalid-string' for issue in issues)
    assert members['user_strings']['state'] == ('partial' if expected_issues else 'complete')
    assert members['coverage']['state'] == 'complete'


# --- managed.native_boundaries -----------------------------------------------------------------------------------------

def test_module_refs_and_pinvoke_rows_against_import_attributes(native, oracle):
    assert [(row['token'], row['name']) for row in native['module_refs']] == [(row['token'], row['name']) for row in oracle['module_refs']]
    methods = by_token(oracle['methods'])
    want = {token: row['import'] for token, row in methods.items() if row['import']}
    got = {row['member_token']: row for row in native['pinvoke_imports']}
    assert set(got) == set(want)
    assert sorted(row['token'] for row in native['pinvoke_imports']) == ['0x1c%06x' % index for index in range(1, len(want) + 1)]
    for token, row in got.items():
        expected = want[token]
        assert (row['member_kind'], row['member_name'], row['import_name'], row['import_scope_token'], row['import_scope_name']) == (
            'method', methods[token]['name'], expected['name'], expected['module'], expected['module_name']), token
        assert (row['mapping_flags'], row['mapping_flags_hex']) == (expected['attributes'], '0x%04x' % expected['attributes'])
        assert (row['no_mangle'], row['supports_last_error'], row['char_set'], row['call_convention'], row['best_fit'], row['throw_on_unmappable_char']) == (
            expected['exact_spelling'], expected['set_last_error'], expected['char_set'], expected['call_convention'], expected['best_fit'], expected['throw_on_unmappable_char']), token
        assert row['verification'] == 'managed-declaration-only'


def test_native_implementations_are_the_non_il_and_pinvoke_methods(native, oracle):
    def kind(method):
        impl = method['impl_flags']
        if method['import'] or method['flags'] & 0x2000:
            return 'pinvoke'
        return {1: 'native-body', 3: 'runtime-provided'}.get(impl & 3) or ('unmanaged-method' if impl & 4 else None)
    want = {method['token']: method for method in oracle['methods'] if kind(method)}
    got = by_token(native['native_implementations'])
    assert set(got) == set(want)
    for token, row in got.items():
        method = want[token]
        assert (row['name'], row['rva'], row['flags'], row['impl_flags'], row['boundary_kind'], row['pinvoke_declared']) == (
            method['name'], method['rva'], method['flags'], method['impl_flags'], kind(method), bool(method['import'] or method['flags'] & 0x2000)), token
        assert row['code_type'] == {0: 'il', 1: 'native', 2: 'optil', 3: 'runtime'}[method['impl_flags'] & 3]
        assert row['managed_kind'] == ('unmanaged' if method['impl_flags'] & 4 else 'managed')
    assert native['summary'] == {'module_ref_count': len(oracle['module_refs']), 'pinvoke_import_count': sum(1 for m in oracle['methods'] if m['import']),
                                 'native_implementation_count': len(want), 'ready_to_run': False, 'mixed_mode_or_native_header': False}


def test_cli_native_facets_follow_the_header_flags(native, oracle):
    flags = oracle['cli']['flags']
    assert native['cli_native'] == {
        'il_only': bool(flags & 1), 'requires_32bit': bool(flags & 2) and not flags & 0x20000, 'strong_name_signed': bool(flags & 8),
        'native_entry_point': bool(flags & 0x10), 'ready_to_run_signature': False,
        'managed_native_header_rva': oracle['cli']['managed_native_header']['rva'], 'managed_native_header_size': oracle['cli']['managed_native_header']['size']}


# --- managed.members: selection parameters -----------------------------------------------------------------------------

def ldstr_tokens(oracle, method_tokens):
    return {row['operand'] for method in oracle['methods'] if method['body'] and method['token'] in method_tokens
            for row in method['body']['instructions'] if row['opcode'] == 'ldstr'}


def check_view(oracle, full, view, types, methods):
    """A selection holds the oracle's own rows for the chosen types and methods, byte-for-byte the rows of the full inventory."""
    keep_types = {row['token'] for row in oracle['type_defs']} if types is None else types
    keep_fields = {row['token'] for row in oracle['fields'] if row['declaring_type'] in keep_types}
    for key, rows, keep in (('types', oracle['type_defs'], keep_types), ('fields', oracle['fields'], keep_fields), ('methods', oracle['methods'], methods)):
        assert [row['token'] for row in view[key]] == [row['token'] for row in rows if row['token'] in keep], key
        assert view[key] == [row for row in full[key] if row['token'] in keep], key
    sites = [(method['token'], site) for method in oracle['methods'] if method['token'] in methods and method['body'] for site in method['body']['call_sites']]
    assert Counter((edge['caller_token'], edge['opcode'], edge['target_token']) for edge in view['call_edges']) == Counter((token, site['opcode'], site['token']) for token, site in sites)
    accesses = [(method['token'], site) for method in oracle['methods'] if method['token'] in methods and method['body'] for site in method['body']['field_sites']]
    assert Counter((row['method_token'], row['opcode'], row['field_token']) for row in view['field_accesses']) == Counter((token, site['opcode'], site['token']) for token, site in accesses)
    assert view['call_edges'] == [edge for edge in full['call_edges'] if edge['caller_token'] in methods]
    assert view['field_accesses'] == [row for row in full['field_accesses'] if row['method_token'] in methods]
    # References and forwarders belong to the assembly, not to a declaring type.
    assert view['member_refs'] == full['member_refs'] and view['exported_types'] == full['exported_types']
    assert view['coverage']['state'] == 'complete'
    if view['user_strings'] is not None:
        tokens, strings = ldstr_tokens(oracle, methods), by_token(oracle['user_strings'])
        assert {row['token'] for row in view['user_strings']['literals']} == tokens
        assert {issue['scope'] for issue in view['user_strings']['issues']} == {
            'metadata.#US:' + token for token in tokens if flag_disagrees(strings[token])}


def chosen_types(oracle):
    """The busiest top-level type and one nested type that has methods."""
    defs = oracle['type_defs']
    top = max((row for row in defs if row['enclosing'] is None), key=lambda row: len(row['method_rows']))
    nested = [row for row in defs if row['enclosing'] is not None and row['method_rows']]
    return [top] + nested[:1]


def with_types(oracle, rows):
    names = [qualified(row) for row in rows]
    tokens = {row['token'] for row in oracle['type_defs'] if qualified(row) in names}
    return names, tokens, {row['token'] for row in oracle['methods'] if row['declaring_type'] in tokens}


def test_type_names_select_exact_types_with_their_members_and_report_unmatched_names(lab, name, oracle, members):
    names, tokens, methods = with_types(oracle, chosen_types(oracle))
    given = names + ['Does.Not.Exist', names[0]]
    view = lab.product(name, 'managed.members', {'type_names': given})
    assert view['selection'] == {'type_names': given, 'unmatched_type_names': ['Does.Not.Exist']}
    assert methods and 0 < len(view['types']) < len(members['types'])
    check_view(oracle, members, view, tokens, methods)


def test_method_window_slices_the_method_rows_and_keeps_the_rest_of_the_inventory(lab, name, oracle, members):
    total = len(oracle['methods'])
    windows = [(total // 3, 7), (total - 3, None), (None, 4), (0, 0), (total + 10, 5), (total, 0)]
    for offset, limit in windows:
        parameters = {key: value for key, value in (('method_offset', offset), ('method_limit', limit)) if value is not None}
        view = lab.product(name, 'managed.members', parameters)
        start = offset or 0
        window = {row['token'] for row in oracle['methods'][start:total if limit is None else start + limit]}
        assert view['selection'] is None, parameters
        check_view(oracle, members, view, None, window)
    assert lab.product(name, 'managed.members', {'method_limit': 0})['methods'] == []


def test_method_window_applies_to_the_assembly_method_list_before_the_type_selection(lab, name, oracle, members):
    names, tokens, methods = with_types(oracle, chosen_types(oracle)[:1])
    rows = [row['token'] for row in oracle['methods']]
    first = min(rows.index(token) for token in methods)
    for offset, limit in ((first, 2), (0, 1)):
        view = lab.product(name, 'managed.members', {'type_names': names, 'method_offset': offset, 'method_limit': limit})
        window = {token for token in rows[offset:offset + limit] if token in methods}
        assert (window != set()) == (offset == first)
        assert view['selection'] == {'type_names': names, 'unmatched_type_names': []}
        check_view(oracle, members, view, tokens, window)


def test_user_strings_can_be_left_out_without_changing_anything_else(lab, name, members):
    view = lab.product(name, 'managed.members', {'user_strings': False})
    assert view['user_strings'] is None and members['user_strings'] is not None
    for key in ('types', 'fields', 'methods', 'member_refs', 'call_edges', 'field_accesses', 'exported_types', 'coverage'):
        assert view[key] == members[key], key


def test_type_names_match_the_bare_case_sensitive_name_and_nothing_else(lab, name, oracle):
    top, nested = chosen_types(oracle)[0], (chosen_types(oracle) + [None])[1]
    given = [qualified(top).swapcase()] + ([qualified(next(row for row in oracle['type_defs'] if row['token'] == nested['enclosing'])) + '/' + nested['name']] if nested else [])
    assert not {qualified(row) for row in oracle['type_defs']} & set(given)
    view = lab.product(name, 'managed.members', {'type_names': given})
    assert view['selection'] == {'type_names': given, 'unmatched_type_names': given}
    check_view(oracle, lab.product(name, 'managed.members'), view, set(), set())


def test_empty_type_name_list_is_rejected_before_a_job_starts(lab, tmp_path):
    from fastapi.testclient import TestClient
    from theseus.api import create_app
    app = create_app(tmp_path / 'data')
    project = app.state.store.create_project('Empty selection')
    artifact = app.state.store.add_artifact(project['id'], lab.assembly(VARIANTS[0]))
    with TestClient(app, base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        reply = client.post(f"/api/projects/{project['id']}/artifacts/{artifact['id']}/analyses",
                            json={'operation': 'managed.members', 'parameters': {'type_names': []}})
        assert reply.status_code == 400 and 'type_names' in reply.text
        analyses = app.state.store.directory / 'analyses'
        assert not analyses.exists() or not any(analyses.iterdir())


# --- digests: recomputed here from the oracle's rows and raw blobs ------------------------------------------------------

OPERAND_KINDS = {'ldstr': 'string', 'call': 'method', 'callvirt': 'method', 'newobj': 'method', 'ldftn': 'method', 'ldfld': 'field', 'stsfld': 'field',
                 'castclass': 'type', 'box': 'type', 'br': 'branch', 'br.s': 'branch', 'brtrue.s': 'branch', 'leave': 'branch', 'switch': 'switch',
                 'ldc.i4': 'constant', 'ldc.i4.s': 'constant', 'ldloc.s': 'variable', 'ldarg.s': 'variable', 'calli': 'signature'}


def test_normalized_il_digest_hashes_the_opcode_kind_operand_triples_of_the_decoded_body(members):
    checked = 0
    for method in members['methods']:
        body = method['body']
        if body['status'] != 'present':
            assert body['normalized_il_sha256'] is None, method['token']
            continue
        triples = [[row['opcode'], row['operand_kind'], row['operand']] for row in body['instructions']]
        assert body['normalized_il_sha256'] == sha(json.dumps(triples, separators=(',', ':'), ensure_ascii=False).encode('utf8')), method['token']
        assert body['anchors'] == [{'il_offset': row['il_offset'], 'opcode': row['opcode'], 'operand_kind': row['operand_kind'], 'operand': row['operand']}
                                   for row in body['instructions'] if row['operand_kind'] != 'none'], method['token']
        for row in body['instructions']:
            assert OPERAND_KINDS.get(row['opcode'], row['operand_kind']) == row['operand_kind'], (method['token'], row)
        checked += 1
    assert checked > 0


def type_operands(blob):
    """(start, end, coded index) of every TypeDefOrRefOrSpecEncoded in a field or method signature, in blob order (ECMA-335 II.23.2)."""
    found = []

    def compressed(at):
        first = blob[at]
        if first < 0x80:
            return first, at + 1
        if first < 0xc0:
            return ((first & 0x3f) << 8) | blob[at + 1], at + 2
        return ((first & 0x1f) << 24) | (blob[at + 1] << 16) | (blob[at + 2] << 8) | blob[at + 3], at + 4

    def coded(at):
        value, end = compressed(at)
        found.append((at, end, value))
        return end

    def modifiers(at):
        while blob[at] in (0x1f, 0x20):
            at = coded(at + 1)
        return at

    def kind(at):
        tag, at = blob[at], at + 1
        if 0x01 <= tag <= 0x0e or tag in (0x16, 0x18, 0x19, 0x1c):
            return at
        if tag in (0x0f, 0x1d):
            return kind(modifiers(at))
        if tag in (0x10, 0x45):
            return kind(at)
        if tag in (0x11, 0x12):
            return coded(at)
        if tag in (0x13, 0x1e):
            return compressed(at)[1]
        if tag == 0x14:
            at = compressed(kind(at))[1]  # element type, then rank
            for _ in range(2):
                count, at = compressed(at)
                for _ in range(count):
                    at = compressed(at)[1]
            count, at = compressed(at)
            for _ in range(count):
                at = compressed(at)[1]
            return at
        if tag == 0x15:
            assert blob[at] in (0x11, 0x12)
            at = coded(at + 1)
            count, at = compressed(at)
            for _ in range(count):
                at = kind(at)
            return at
        if tag == 0x1b:
            return signature(at)
        raise ValueError('unsupported element type 0x%02x' % tag)

    def signature(at):
        convention, at = blob[at], at + 1
        if convention & 0x10:
            at = compressed(at)[1]
        count, at = compressed(at)
        for _ in range(count + 1):
            at = kind(modifiers(at))
        return at

    if blob[0] == 0x06:
        kind(modifiers(1))
    else:
        signature(0)
    return found


def reference_digest(oracle, token):
    """TypeRef digest: its own namespace and name after the enclosing TypeRef when the resolution scope is a TypeRef; the scope assembly is not part of it."""
    row = by_token(oracle['type_refs'])[token]
    prefix = bytes([0]) if not row['scope'].startswith('0x01') else bytes([1]) + reference_digest(oracle, row['scope'])
    return bytes.fromhex(sha(prefix + row['namespace'].encode() + bytes([0]) + row['name'].encode()))


def operand_digest(oracle, coded):
    row, table = coded >> 2, coded & 3
    if table == 0:
        return bytes.fromhex(name_digest(oracle, '0x%08x' % (0x02000000 | row)))
    return reference_digest(oracle, '0x%08x' % (0x01000000 | row)) if table == 1 else None


def resolved_digest(oracle, blob):
    """sha256 of the blob with every type operand replaced by 0xff and the 32-byte name digest; none for a TypeSpec operand or a blob outside the grammar."""
    try:
        operands = type_operands(blob)
    except (ValueError, IndexError):
        return None
    digest, copied = hashlib.sha256(), 0
    for start, end, coded in operands:
        named = operand_digest(oracle, coded)
        if named is None:
            return None
        digest.update(blob[copied:start] + bytes([0xff]) + named)
        copied = end
    digest.update(blob[copied:])
    return digest.hexdigest()


def test_resolved_signature_digest_replaces_every_type_operand_by_the_name_digest(members, oracle, name):
    replaced = unchanged = 0
    for key in ('fields', 'methods', 'member_refs'):
        want = by_token(oracle[key])
        for row in members[key]:
            blob = bytes.fromhex(want[row['token']]['signature'])
            assert row['signature']['resolved_sha256'] == resolved_digest(oracle, blob), (key, row['token'], row['name'])
            if row['signature']['resolved_sha256'] is not None:
                changed = row['signature']['resolved_sha256'] != row['signature']['raw_sha256']
                replaced, unchanged = replaced + changed, unchanged + (not changed)
    # The synthetic assembly's signatures name no types, so there nothing is replaced.
    assert (replaced > 20 and unchanged > 0) or name == 'synthetic-opcodes' and replaced == 0 and unchanged > 0


BUILD_PAIRS = [('net8-anycpu', 'net8-x64-debug-signed'), ('fw-anycpu', 'fw-x86-unoptimised')]


def build_independent_key(row, kind):
    return (row['declaring_type'], row['name'], row['flags'], kind(row))


@pytest.mark.parametrize('pair', BUILD_PAIRS, ids=['-vs-'.join(pair) for pair in BUILD_PAIRS])
def test_same_source_gives_the_same_resolved_signature_digests_in_different_builds(lab, pair):
    left, right = (lab.product(name, 'managed.members') for name in pair)
    kinds = {'methods': lambda row: (row['signature']['parameter_count'], row['signature']['generic_parameter_count']), 'fields': lambda row: 0}
    for key, kind in kinds.items():
        rows = []
        for document in (left, right):
            index = Counter(build_independent_key(row, kind) for row in document[key])
            rows.append({build_independent_key(row, kind): row for row in document[key] if index[build_independent_key(row, kind)] == 1})
        shared = rows[0].keys() & rows[1].keys()
        assert len(shared) > len(rows[0]) // 2, key
        for member in shared:
            assert rows[0][member]['signature']['resolved_sha256'] == rows[1][member]['signature']['resolved_sha256'], member


def test_token_free_method_bodies_have_identical_digests_in_two_builds_of_the_same_source(lab):
    left, right = lab.product('fw-anycpu', 'managed.members'), lab.product('fw-pref32-exe-signed', 'managed.members')
    kind = lambda row: (row['signature']['parameter_count'], row['signature']['generic_parameter_count'])

    def stable(document):
        counts = Counter(build_independent_key(row, kind) for row in document['methods'])
        return {build_independent_key(row, kind): row['body'] for row in document['methods']
                if counts[build_independent_key(row, kind)] == 1 and row['body']['status'] == 'present' and all(i['operand_kind'] in ('none', 'branch', 'constant', 'variable', 'switch') for i in row['body']['instructions'])}
    first, second = stable(left), stable(right)
    shared = first.keys() & second.keys()
    assert len(shared) >= 5
    for member in shared:
        assert (first[member]['il_sha256'], first[member]['normalized_il_sha256']) == (second[member]['il_sha256'], second[member]['normalized_il_sha256']), member

    # Every other body differs only in build-local tokens: the opcodes, operand kinds, offsets and token-free operands agree.
    def shape(document):
        counts = Counter(build_independent_key(row, kind) for row in document['methods'])
        return {build_independent_key(row, kind): [(i['il_offset'], i['opcode'], i['operand_kind'], None if i['operand_kind'] in ('method', 'field', 'type', 'string', 'signature') else i['operand'], i['bytes'] if i['operand_kind'] == 'none' else None) for i in row['body']['instructions']]
                for row in document['methods'] if counts[build_independent_key(row, kind)] == 1 and row['body']['status'] == 'present'}
    first, second = shape(left), shape(right)
    shared = first.keys() & second.keys()
    assert len(shared) > len(first) // 2
    assert all(first[member] == second[member] for member in shared)


# --- the checks must be able to fail ------------------------------------------------------------------------------------

def first_instruction(document, predicate):
    return next(row for method in document['methods'] if method['body']['status'] == 'present' for row in method['body']['instructions'] if predicate(row))


def first_present_body(document):
    return next(method['body'] for method in document['methods'] if method['body']['status'] == 'present')


def poke(path, value):
    def apply(document):
        target = document
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value(target[path[-1]]) if callable(value) else value
    return apply


def drop(key):
    return lambda document: document[key].pop()


def normalized_digest_check(members, oracle):
    test_normalized_il_digest_hashes_the_opcode_kind_operand_triples_of_the_decoded_body(members)


MUTATIONS = [
    ('artifact', test_pe_and_cli_header_match_the_runtime_reader, poke(['pe', 'section_count'], lambda value: value + 1)),
    ('artifact', test_assembly_references, poke(['references', 0, 'name'], lambda value: value + 'x')),
    ('artifact', test_custom_attribute_parents_constructors_and_value_hashes, drop('attributes')),
    ('artifact', test_manifest_resources_including_linked_and_private, poke(['resources', 0, 'data_sha256'], '0' * 64)),
    ('members', test_type_rows_nesting_member_lists_and_name_digests, poke(['types', -1, 'name_sha256'], '0' * 64)),
    ('members', test_field_tokens_names_flags_and_signatures, poke(['fields', 0, 'flags'], lambda value: value ^ 1)),
    ('members', test_method_tokens_names_flags_rva_and_signatures, poke(['methods', 5, 'rva'], lambda value: value + 4)),
    ('members', test_method_bodies_header_il_size_max_stack_locals_and_regions, lambda document: first_present_body(document).update(max_stack=first_present_body(document)['max_stack'] + 1)),
    ('members', test_every_decoded_instruction_matches_offsets_opcodes_operands_and_bytes,
     lambda document: first_instruction(document, lambda row: row['operand'] is not None).update(operand='0x0a00ffff')),
    ('members', test_member_refs_parents_names_and_signatures, poke(['member_refs', 0, 'name'], lambda value: value + 'x')),
    ('members', test_call_edges_equal_the_il_call_sites_of_every_method, drop('call_edges')),
    ('members', test_field_accesses_equal_the_il_field_sites_of_every_method, poke(['field_accesses', 0, 'field_name'], lambda value: value + 'x')),
    ('members', test_exported_types_forwarders_and_nested_forwarders, poke(['exported_types', 0, 'name'], lambda value: value + 'x')),
    ('members', test_user_string_literals_and_their_terminal_flag_diagnostics, poke(['user_strings', 'literals', 0, 'value'], lambda value: value + 'x')),
    ('members', normalized_digest_check,
     lambda document: first_present_body(document).update(normalized_il_sha256='0' * 64)),
    ('native', test_module_refs_and_pinvoke_rows_against_import_attributes, poke(['pinvoke_imports', 0, 'import_name'], lambda value: value + 'x')),
    ('native', test_native_implementations_are_the_non_il_and_pinvoke_methods, drop('native_implementations')),
    ('native', test_cli_native_facets_follow_the_header_flags, poke(['cli_native', 'il_only'], lambda value: not value)),
]


@pytest.mark.parametrize('document, check, mutate', MUTATIONS, ids=[check.__name__[5:50] for _, check, _ in MUTATIONS])
def test_each_check_fails_when_the_product_document_is_altered(lab, document, check, mutate):
    operation = {'artifact': 'managed.artifact', 'members': 'managed.members', 'native': 'managed.native_boundaries'}[document]
    original, oracle = lab.product(VARIANTS[0], operation), lab.oracle(VARIANTS[0])
    check(original, oracle)
    altered = copy.deepcopy(original)
    mutate(altered)
    assert altered != original
    with pytest.raises(AssertionError):
        check(altered, oracle)


def test_resolved_digest_check_fails_when_a_digest_is_altered(lab):
    members, oracle = lab.product(VARIANTS[0], 'managed.members'), lab.oracle(VARIANTS[0])
    altered = copy.deepcopy(members)
    row = next(row for row in altered['methods'] if row['signature']['resolved_sha256'] != row['signature']['raw_sha256'] and row['signature']['resolved_sha256'])
    row['signature']['resolved_sha256'] = '0' * 64
    with pytest.raises(AssertionError):
        test_resolved_signature_digest_replaces_every_type_operand_by_the_name_digest(altered, oracle, VARIANTS[0])


def test_selection_check_fails_when_a_selected_row_or_edge_is_missing(lab):
    oracle, full = lab.oracle(VARIANTS[0]), lab.product(VARIANTS[0], 'managed.members')
    names, tokens, methods = with_types(oracle, chosen_types(oracle))
    view = lab.product(VARIANTS[0], 'managed.members', {'type_names': names})
    check_view(oracle, full, view, tokens, methods)
    tested = 0
    for mutate in (lambda doc: doc['methods'].pop(), lambda doc: doc['call_edges'].pop(), lambda doc: doc['types'].pop(), lambda doc: doc['user_strings'].update(literals=[])):
        altered = copy.deepcopy(view)
        mutate(altered)
        if altered == view:
            continue  # nothing to drop: the selection has no user strings
        tested += 1
        with pytest.raises(AssertionError):
            check_view(oracle, full, altered, tokens, methods)
    assert tested >= 3


def test_compiled_latin1_literals_carry_the_compiler_flag_without_an_issue(members, oracle):
    rows = [row for row in oracle['user_strings'] if row['referenced_by_ldstr'] and compiler_flag(row)]
    if not rows:
        pytest.skip('This variant has no literal whose only flag trigger is a unit in 0x80-0xFF')
    scopes = {issue['scope'] for issue in members['user_strings']['issues']}
    assert not any('metadata.#US:' + row['token'] in scopes for row in rows)
