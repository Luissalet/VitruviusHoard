# Personal banking example

A `vitruvius-app/v2` application with simulated data: a fictitious bank, invented people and IBANs with valid check digits. It shows accounts, balances, movements, contacts and a transfer flow (data, confirmation, receipt with undo).

- Collections: `cuentas`, `contactos`, `movimientos`. Money is stored in integer cents.
- Action `transferir`: one source account and exactly one of `contacto`, `destino` (own account) or `iban` (with `beneficiario`). It debits `disponible_cent` (minimum 0, so a card can spend its credit) and `saldo_cent`, records the movement and credits an own destination, found by id or by IBAN, in the same transaction.
- The transfer page gives the shared transfer assistant its own place: `data-transfer-scope` on the form and panel, `data-transfer-slot` on origin (`source`), contact (`recipient`), IBAN, amount (`amountCents`) and reference (`concept`), and a manual mount in `aside#voz`. `assets/transfer.js` passes the bank's accounts, contacts and `transferir` action to the panel, marks the missing fields and opens the confirmation step with the data the assistant read. A fixed **Asistente** control on every page leads to it; on a phone the panel is a compact sheet. The page also exposes `window.teselaTransfer` (`set`, `review`, `confirm`, `undo`, `findContacts`).
- Motion follows the library durations and ease-out curves (balance and bar on entry, step changes, filled fields) and stops under reduced motion.

Create it with `app_project_create` (`template: "custom"`) passing every file in this folder except this README as `files`; the tool adds the current runtime as `server.py`. Add the assistant files under `assets/transfer-assistant/` from the read-only `app_transfer_assistant_assets` tool.
