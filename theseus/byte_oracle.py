"""Compare retained decoder observations without erasing referenced constants."""
def _project(snapshot):
    projected, unknowns = [], []
    for index, instruction in enumerate(snapshot["instructions"]):
        code = bytearray.fromhex(instruction["bytes"])
        masks = {row["operand_index"]: row["mask_hex"] for row in instruction["operand_value_masks"]}
        references = instruction["referenced_targets"]
        targets = []
        for reference in references:
            kind = reference["target_kind"]
            if kind == "function-local-code":
                identity = {"kind": kind, "offset": reference["function_offset"]}
            elif kind == "data" and reference.get("status") == "observed":
                identity = {"kind": kind, **{key: reference[key] for key in
                    ("data_type", "data_length", "data_offset", "bytes_hex")}}
            else:
                unknowns.append({"instruction_index": index, "reference": reference,
                                 "reason": "Reference extent or boundary is unresolved"})
                identity = {"kind": "unknown", "reference": reference}
            identity.update(operand_index=reference["operand_index"], type=reference["type"])
            targets.append(identity)
        operands = []
        for operand in instruction["operands"]:
            # A proven reference and decoder mask must agree before address bits
            # are normalized. Literal scalars without a reference stay exact.
            matches = [ref for ref in references if ref["operand_index"] == operand["index"]]
            normalized = matches and all(ref["target_kind"] == "function-local-code" or
                (ref["target_kind"] == "data" and ref.get("status") == "observed") for ref in matches)
            raw_mask = masks.get(operand["index"])
            mask = bytes.fromhex(raw_mask) if raw_mask is not None else None
            normalized = bool(normalized and mask is not None and len(mask) == len(code) and any(mask))
            if normalized:
                for position, value in enumerate(mask):
                    code[position] &= ~value & 255
                components = [{"kind": "resolved-reference", "targets": [row for row in targets
                               if row["operand_index"] == operand["index"]]}]
            else:
                components = [{key: value for key, value in item.items() if key != "text"}
                              for item in operand["components"]]
            operands.append({"index": operand["index"], "components": components})
        projected.append({"offset": instruction["function_offset"], "mnemonic": instruction["mnemonic"],
                          "length": instruction["length"], "bytes_hex": code.hex(), "operands": operands,
                          "targets": targets, "flow": {key: instruction["flow"][key]
                              for key in ("kind", "conditional", "computed")}})
        if instruction["flow"]["computed"]:
            unknowns.append({"instruction_index": index, "reason": "Computed flow has unresolved runtime destinations"})
    if not projected:
        unknowns.append({"reason": "The function has no decoded instructions"})
    return projected, unknowns


def compare(reference, candidate):
    left, left_unknown = _project(reference)
    right, right_unknown = _project(candidate)
    differences = []
    if reference["architecture"] != candidate["architecture"]:
        differences.append({"field": "architecture", "reference": reference["architecture"], "candidate": candidate["architecture"]})
    for index in range(max(len(left), len(right))):
        before = left[index] if index < len(left) else None
        after = right[index] if index < len(right) else None
        if before != after:
            differences.append({"instruction_index": index, "reference": before, "candidate": after})
    unknowns = [{"side": "reference", **row} for row in left_unknown] + [
                {"side": "candidate", **row} for row in right_unknown]
    # Unresolved addresses can differ because of layout alone. Do not claim a
    # proven mismatch solely from those observations.
    definite = [row for row in differences if row.get("field") == "architecture" or
                not any(item.get("instruction_index") == row.get("instruction_index") for item in unknowns)]
    return {"status": "different" if definite else "unknown" if unknowns or differences else "equal-observed",
            "differences": differences, "unknowns": unknowns,
            "reference_projection": left, "candidate_projection": right,
            "limitations": ["Equality covers these selected decoded functions and exact observed referenced data, not whole-program behavior.",
                            "Only value bits of operands with resolved local-code or defined-data references are normalized.",
                            "Undefined data extents, external callees and computed flow remain unknown."]}
