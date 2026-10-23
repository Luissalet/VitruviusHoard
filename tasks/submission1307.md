# Exact native names and conditional inventory base

Two retained product compositions join the existing native session API/MCP/form.
Exact name resolution keeps aliases, distinguishes absence/ambiguity/provider
errors and uses numeric xrefs. Overview retains the full raw inventory and
consolidates base plus address space only from agreeing observed facts. Existing
primitives and lifecycle behavior remain available.

Initial composition tests:25PASS. The first real ELF/Ghidra run reached and
passed the symbol/caller/segment/base/.text checks, then failed in the test reader
at `records[row].value`: listing returns record keys, not contents. XML/log and
basetemp1307-b remain intact. Correcting only that reader yielded1PASS in1307-c,
including close with native exit0 and two exact document transfers after parking
the unchanged original. A subsequent address-normalization refinement deduplicates
equivalent hex forms and rejects invalid address observations.

The combined area run1307-d passed47 cases across native inventory, context and
sessions, including native annotation/reopen and raw6502 coverage. A subsequent
reference-address validation change and stronger discovery assertion passed31
inventory cases in1307-e, including the complete original ELF/Ghidra/transfer
case. These are separate runs, with fresh basetemps; neither is a full regression.

Source review, full regression, normal package, private installed MCP/UI and
independent installed acceptance are pending.
No coverage row is promoted by this submission draft;1040/1157 remain open.
W4 remains published separately atbe61ee3 with its own evidence and wheel.
