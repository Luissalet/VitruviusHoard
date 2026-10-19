using System;
using System.Runtime.InteropServices;
public class Gauge<T> {
    public double Limit { get; set; }
    public event Action Changed;
    public Gauge() { Limit = 128.0; }
    public string Read(int input) {
        try { if (input < 0) throw new ArgumentException("año"); return (input * 7).ToString(); }
        catch (ArgumentException) { return "negative"; }
        finally { if (Changed != null) Changed(); }
    }
    public class Nested { public int Value; }
    public enum Mode { Idle = 3, Active = 9 }
}
public static class NativeEdge {
    [DllImport("kernel32.dll", EntryPoint="GetTickCount")]
    public static extern uint Clock();
}
