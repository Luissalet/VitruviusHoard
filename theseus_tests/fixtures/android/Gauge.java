package com.theseus.fixture;

public class Gauge {
    public static final String MARKER = initialize();
    private static String initialize() { return "THeseus format fixture"; }
    public int normalize(int value) { return value < 0 ? -1 : value + 128; }
    public String normalize(String value) { return value.trim(); }
    public int twice(int value) { return normalize(value) + normalize(value + 1); }
    public native long readNativeClock();
    public class Probe { public int read(int value) { return normalize(value); } }
}
