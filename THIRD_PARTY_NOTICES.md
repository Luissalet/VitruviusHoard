# Third-party notices

## Isometric figure kit (MIT)

`vitruvius_hoard/diagrams/iso.py` is a Python port of the maths and drawing primitives of an MIT-licensed isometric figure
kit written in JavaScript: the camera and projection, the fit to the canvas, extruded solids with their visible faces and
four tones, cylinders, ticks, coils, knurls, seams and text on faces. The painter's order, the brand tones, the frame, the
parametric pieces and the gates in `vitruvius_hoard/diagrams/isometric.py` are new code written for this project, guided by the
same craft rules (tone hierarchy with one lit piece, lines that end on something).

```
MIT License

Copyright (c) 2026 Ryan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Design rules and themes (see NOTICE)

The registry in `vitruvius_hoard/rules/` is original Python guided by the descriptions of an Apache-2.0 detector set (impeccable,
Copyright 2025 Paul Bakaus, https://github.com/pbakaus/impeccable) and by the gate list of an MIT design skill (hallmark,
Copyright (c) 2026 Hallmark contributors, https://github.com/Nutlope/hallmark). `vitruvius_hoard/themes.json` holds theme headers
from the second one as data. The MIT licence text is the same as above with that copyright line; the Apache-2.0 text is at
https://www.apache.org/licenses/LICENSE-2.0 and covers the studied material. No source file was copied; the root `NOTICE` lists
what was used and how.

```
MIT License

Copyright (c) 2026 Hallmark contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files
(the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Sound effects library (earshot, MIT)

Optional dependency used for the sound track of motion compositions (its effect bank and kit only). Not copied into this repository;
installed with `pip install --no-deps` from https://github.com/Leonxlnx/earshot at commit 591fa3e028032e6dce56620a20e932e35667e8d8.

```
MIT License

Copyright (c) 2026 Leon Lin

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files
(the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Swift demangling test vectors

`theseus_tests/fixtures/swift_manglings.txt` is an unmodified copy of `test/Demangle/Inputs/manglings.txt`
from https://github.com/swiftlang/swift at tag `swift-6.4.1-RELEASE`. It is used only as test data to check
the demangler output against the expectations of the Swift project's own test suite.

Copyright Apple Inc. and the Swift project authors.
Licensed under the Apache License, Version 2.0 with Runtime Library Exception
(https://swift.org/LICENSE.txt). See https://swift.org/CONTRIBUTORS.txt for the list of Swift project authors.
