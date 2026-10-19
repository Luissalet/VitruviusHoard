"""Original 8N1 UART A5 recording: one byte-wide logic sample, ten samples/bit."""
def uart_recording():
    samples = [1]*20
    for byte in b'A5':
        for bit in [0,*[(byte>>index)&1 for index in range(8)],1]:
            samples.extend([bit]*10)
    return bytes(samples+[1]*20)
