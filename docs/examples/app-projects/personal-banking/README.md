# Personal banking example

A `vitruvius-app/v2` application with simulated data: a fictitious bank, invented people and IBANs with valid check digits. It shows accounts, balances, movements, contacts and a transfer flow (data, confirmation, receipt with undo).

- Collections: `cuentas`, `contactos`, `movimientos`. Money is stored in integer cents.
- Action `transferir`: one source account and exactly one of `contacto`, `destino` (own account) or `iban` (with `beneficiario`). It debits `disponible_cent` (minimum 0, so a card can spend its credit) and `saldo_cent`, records the movement and credits an own destination, found by id or by IBAN, in the same transaction.
- The transfer page marks its fields with `data-voice-field`, reserves `aside#voz[data-voice-slot]` for a voice control and exposes `window.teselaTransfer` (`set`, `review`, `confirm`, `undo`, `findContacts`).

Create it with `app_project_create` (`template: "custom"`) passing every file in this folder except this README as `files`; the tool adds the current runtime as `server.py`.
