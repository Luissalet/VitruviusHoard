// Mach-O load-command facts read with Go's debug/macho, printed as JSON for theseus_tests/test_macho_oracle.py.
package main

import (
	"debug/macho"
	"encoding/json"
	"fmt"
	"os"
)

type load struct {
	Cmd     uint32 `json:"cmd"`
	Name    string `json:"name,omitempty"`
	Current string `json:"current_version,omitempty"`
	Compat  string `json:"compatibility_version,omitempty"`
	Value   uint32 `json:"value,omitempty"`
	Offset  uint32 `json:"data_offset,omitempty"`
	Size    uint32 `json:"data_size,omitempty"`
}

type slice struct {
	Offset int64  `json:"offset"`
	Size   int64  `json:"size"`
	Cpu    uint32 `json:"cpu_type"`
	SubCpu uint32 `json:"cpu_subtype"`
	Type   uint32 `json:"file_type"`
	Loads  []load `json:"loads"`
}

func version(v uint32) string { return fmt.Sprintf("%d.%d.%d", v>>16, (v>>8)&0xff, v&0xff) }

func cString(raw []byte, at uint32) string {
	end := int(at)
	for end < len(raw) && raw[end] != 0 {
		end++
	}
	return string(raw[at:end])
}

func read(file *macho.File, offset, size int64) slice {
	order := file.ByteOrder
	out := slice{Offset: offset, Size: size, Cpu: uint32(file.Cpu), SubCpu: file.SubCpu, Type: uint32(file.Type), Loads: []load{}}
	for _, command := range file.Loads {
		raw := command.Raw()
		cmd := order.Uint32(raw)
		row := load{Cmd: cmd}
		switch cmd {
		case 0xc, 0xd, 0x80000018, 0x8000001f, 0x20, 0x80000023:
			row.Name = cString(raw, order.Uint32(raw[8:]))
			row.Current, row.Compat = version(order.Uint32(raw[16:])), version(order.Uint32(raw[20:]))
		case 0x8000001c, 0xe, 0x27:
			row.Name = cString(raw, order.Uint32(raw[8:]))
		case 0x32:
			row.Value = order.Uint32(raw[8:])
		case 0x1d:
			row.Offset, row.Size = order.Uint32(raw[8:]), order.Uint32(raw[12:])
		}
		out.Loads = append(out.Loads, row)
	}
	return out
}

func main() {
	path := os.Args[1]
	var slices []slice
	if fat, err := macho.OpenFat(path); err == nil {
		for _, arch := range fat.Arches {
			slices = append(slices, read(arch.File, int64(arch.Offset), int64(arch.Size)))
		}
	} else {
		file, err := macho.Open(path)
		if err != nil {
			panic(err)
		}
		info, _ := os.Stat(path)
		slices = append(slices, read(file, 0, info.Size()))
	}
	json.NewEncoder(os.Stdout).Encode(slices)
}
