# License and Attribution for eBUS Configuration Files

This directory (`ebusd-configuration/`) contains eBUS configuration and message definition files (`.csv`) for use with the [ebusd](https://github.com/john30/ebusd) daemon.

---

## 1. Upstream-Derived Configuration Files (GPL-3.0)

The following files are derived, adapted, or incorporate baseline definitions from the [john30/ebusd-configuration](https://github.com/john30/ebusd-configuration) repository:

- `broadcast.csv`

These files are licensed under the **GNU General Public License v3.0 (GPL-3.0)**:

> **Copyright (c) John30 and eBUSd contributors**
>
> This program is free software: you can redistribute it and/or modify
> it under the terms of the GNU General Public License as published by
> the Free Software Foundation, either version 3 of the License, or
> (at your option) any later version.
>
> This program is distributed in the hope that it will be useful,
> but WITHOUT ANY WARRANTY; without even the implied warranty of
> MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
> GNU General Public License for more details: <https://www.gnu.org/licenses/gpl-3.0.html>.

---

## 2. Original Reverse-Engineered Files (Dual-Licensed: MIT & GPL-3.0)

The following files were developed through original protocol reverse-engineering on live hardware specifically for the **aroTHERM & GeniaAir (eBUS)** integration:

- `vaillant/08.hmux0.csv`
- `vaillant/15.bass3.csv`
- `vaillant/15.basv3.csv`
- `vaillant/76.vwzio.csv`
- `vaillant/04.netx3.csv`
- `vaillant/f6.netx3.csv`

To facilitate both direct use within the MIT-licensed Home Assistant integration and seamless contribution upstream into the GPL-3.0 eBUSd ecosystem, these files are **dual-licensed** under:

1. **The MIT License** (Copyright (c) 2026 R91g) — terms below.
2. **GNU General Public License v3.0 (GPL-3.0)** — at your option.

### MIT License Terms

```text
MIT License

Copyright (c) 2026 R91g

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

---

## 3. Home Assistant Integration License

The Python source code of the Home Assistant custom integration (`custom_components/arotherm_genia_ebusd/`) and unit tests are separately licensed under the **MIT License** (see the root [`../LICENSE`](../LICENSE) file).
