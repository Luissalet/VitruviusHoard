import assert from "node:assert/strict";
import {test} from "node:test";
import {initialTransfer, parseAmount, transferTurn} from "../vitruvius_hoard/transfer_assistant/dialogue.js";

const context = {
  contacts: [
    {id: "ana", name: "Ana Prado"},
    {id: "marta", name: "Marta Vidal"},
    {id: "maria-uno", name: "María Sierra"},
    {id: "maria-dos", name: "María Vela"},
  ],
  accounts: [
    {id: "daily", name: "Cuenta diaria", aliases: ["diaria", "current"], balanceCents: 150000},
    {id: "reserve", name: "Ahorro", aliases: ["savings"], balanceCents: 3000},
  ],
};

function conversation(...messages) {
  let state = initialTransfer();
  return messages.map(text => {
    const turn = transferTurn(state, text, context);
    state = turn.state;
    return turn;
  });
}

const complete = "Haz una transferencia a Marta de 40 euros con concepto cena desde la cuenta diaria";

test("(a) all slots at once and a later explicit confirmation", () => {
  const [draft, confirmed] = conversation(complete, "Sí, confirmo");
  assert.equal(draft.state.phase, "ready");
  assert.equal(draft.action, undefined);
  assert.match(draft.message, /40,00.*Marta Vidal.*Cuenta diaria.*cena.*Confirmas/);
  assert.deepEqual(confirmed.action, {
    recipient: {id: "marta", name: "Marta Vidal"}, amountCents: 4000, concept: "cena", source: "daily",
  });
});

test("(b) asks for the first missing slot and accepts one answer at a time", () => {
  const turns = conversation("Haz una transferencia", "Ana", "20,60 euros", "Clase de baile a las ocho", "Diaria", "¿Confirmas?");
  assert.deepEqual(turns.slice(0, 4).map(turn => turn.state.next), ["recipient", "amountCents", "concept", "source"]);
  assert.equal(turns[4].state.phase, "ready");
  assert.equal(turns[4].state.slots.concept, "Clase de baile a las ocho");
  assert.equal(turns[4].state.slots.amountCents, 2060);
  assert.equal(turns[5].action, undefined);
});

test("(c) collects independent slots out of order and preserves literal reference", () => {
  const turns = conversation("Desde ahorro", "Por quince euros y cincuenta céntimos", "A Ana", "Concepto Clases de canto");
  assert.equal(turns[1].state.slots.source, "reserve");
  assert.equal(turns[1].state.slots.amountCents, 1550);
  assert.equal(turns[3].state.phase, "ready");
});

test("(d) corrections replace slots and require another explicit confirmation", () => {
  const [draft, amount, recipient, confirmed] = conversation(complete, "No, mejor sesenta", "A Marta no, a Ana", "confirmo");
  assert.equal(draft.state.slots.amountCents, 4000);
  assert.equal(amount.state.slots.amountCents, 6000);
  assert.equal(amount.action, undefined);
  assert.equal(recipient.state.slots.recipient.id, "ana");
  assert.equal(recipient.action, undefined);
  assert.equal(confirmed.action.recipient.id, "ana");
});

test("(e) same given name requires a chosen contact", () => {
  const [turn, earlyYes, picked] = conversation("A María por 20 euros, concepto regalo desde diaria", "sí", "María Vela");
  assert.deepEqual(turn.state.candidates.map(item => item.id), ["maria-uno", "maria-dos"]);
  assert.match(turn.message, /María Sierra o María Vela/u);
  assert.equal(earlyYes.action, undefined);
  assert.equal(picked.state.phase, "ready");
  assert.equal(picked.state.slots.recipient.id, "maria-dos");
});

test("(f) cancelling the reviewed draft leaves nothing a later yes can execute", () => {
  const [, cancelled, repeated] = conversation(complete, "Cancela la transferencia", "sí");
  assert.equal(cancelled.state.phase, "cancelled");
  assert.deepEqual(cancelled.state.slots, {});
  assert.equal(repeated.action, undefined);
});

test("(g) low balance blocks confirmation, then accepts an amended amount", () => {
  const [low, earlyYes, amended, confirmed] = conversation(complete.replace("diaria", "ahorro"), "sí", "Mejor veinte euros", "sí");
  assert.equal(low.state.phase, "insufficient");
  assert.match(low.message, /Saldo insuficiente/);
  assert.equal(earlyYes.action, undefined);
  assert.equal(amended.state.phase, "ready");
  assert.equal(confirmed.action.amountCents, 2000);
});

test("validates IBAN and never extracts digits from a reference or an IBAN", () => {
  // The check digits for the synthetic all-zero BBAN are 82.
  const [valid] = conversation("Haz una transferencia a ES82 0000 0000 0000 0000 0000 por 12,50 €, concepto curso 2027 desde diaria");
  assert.equal(valid.state.phase, "ready");
  assert.equal(valid.state.slots.recipient.iban, "ES8200000000000000000000");
  assert.equal(valid.state.slots.amountCents, 1250);
  const [invalid] = conversation("A ES83 0000 0000 0000 0000 0000");
  assert.equal(invalid.state.next, "recipient");
  const [reference] = conversation("A Ana, concepto sesión 42 desde diaria");
  assert.equal(reference.state.next, "amountCents");
  assert.equal(reference.state.slots.amountCents, undefined);
});

test("amount parsing uses integer cents and rejects negative, zero, precision and malformed text", () => {
  for (const [text, cents] of [["1.234,56 €", 123456], ["sesenta y cinco", 6500], ["mil doscientos treinta", 123000],
    ["12 euros con 3 céntimos", 1203], ["doce coma tres", 1230], ["-5 euros", null], ["0", null], ["1,234", null],
    ["60 o 70", null], ["30 000", null], ["60 70", null]]) {
    assert.equal(parseAmount(text), cents, text);
  }
  assert.equal(parseAmount("€1,234.56", "en"), 123456);
  assert.equal(parseAmount("one hundred and forty-five euros", "en"), 14500);
});

test("English all-at-once and disables spoken confirmation when the action is not declared", () => {
  const en = {...context, lang: "en", allowConfirm: false};
  const draft = transferTurn(initialTransfer(), "Send 50 euros to Ana from current with reference Sunday lunch", en);
  assert.equal(draft.state.phase, "ready");
  assert.match(draft.message, /Sunday lunch/);
  assert.equal(transferTurn(draft.state, "yes", en).action, undefined);
  assert.equal(transferTurn(draft.state, "yes", {...en, allowConfirm: true}).action.amountCents, 5000);
});

test("partial or composite confirmation never releases the action", () => {
  const [draft, mixed] = conversation(complete, "Sí, mejor sesenta");
  assert.equal(draft.state.phase, "ready");
  assert.equal(mixed.action, undefined);
  assert.equal(mixed.state.slots.amountCents, 6000);
});



test("only final, cited structured fields can supplement an unrecognised phrase", () => {
  const raw = "Doce y medio para la destinataria habitual";
  const interpretation = {
    is_final: true,
    changed: ["destination_contact_id", "amount_cents", "concept"],
    fields: {
      destination_contact_id: {value: "ana", quote: "destinataria habitual", validation: "valid"},
      amount_cents: {value: 1250, quote: "Doce y medio", validation: "valid"},
      concept: {value: "no aparece", quote: "inventado", validation: "valid"},
      source_account_id: {value: "daily", quote: "habitual", validation: "valid"},
    },
  };
  const direct = transferTurn(initialTransfer(), raw, {...context, interpretation});
  assert.equal(direct.state.slots.recipient.id, "ana");
  assert.equal(direct.state.slots.amountCents, 1250);
  assert.equal(direct.state.slots.concept, undefined);
  assert.equal(direct.state.slots.source, undefined);
  assert.equal(direct.action, undefined);
  const provisional = transferTurn(initialTransfer(), raw, {...context, interpretation: {...interpretation, is_final: false}});
  assert.equal(provisional.state.slots.recipient, undefined);
});

test("literal confirmation alone can submit, even when service normalisation changes the text", () => {
  const [draft] = conversation(complete);
  const altered = transferTurn(draft.state, "No quiero confirmarlo", {
    ...context, interpretation: {is_final: true, text_clean: "Sí", changed: [], fields: {}},
  });
  assert.equal(altered.action, undefined);
});
