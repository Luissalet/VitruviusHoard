#ifndef BOUND
#define BOUND 128.0
#endif

int _fltused = 0;

__declspec(dllexport) double clamp_value(double input) {
    return input < BOUND ? input : BOUND;
}

__declspec(dllexport) __declspec(noinline) long long normalize_value(long long input) {
    if (input < 0) input = -input;
    return input * 2 + 7;
}

__declspec(dllexport) long long route_value(long long input) {
    return normalize_value(input) + 3;
}
