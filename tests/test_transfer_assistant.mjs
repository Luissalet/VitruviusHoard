import assert from "node:assert/strict";
import {test} from "node:test";
import {initialTransfer, parseAmount, transferSpeech, transferTurn} from "../vitruvius_hoard/transfer_assistant/dialogue.js";
import {speakTransferReply, transcribeTransferSpeech} from "../vitruvius_hoard/transfer_assistant/voice.js";

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
  assert.equal(draft.phraseId, "confirmar");
  assert.match(draft.message, /^¿Confirmas la transferencia.*40,00.*Marta Vidal.*Cuenta diaria.*cena.*\?$/u);
  assert.equal(transferSpeech(draft.message, draft.state, "es"), draft.message);
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
  assert.equal(amount.phraseId, "confirmar");
  assert.equal(amount.action, undefined);
  assert.equal(recipient.state.slots.recipient.id, "ana");
  assert.equal(recipient.phraseId, "confirmar");
  assert.equal(recipient.action, undefined);
  assert.equal(confirmed.action.recipient.id, "ana");
});

test("(e) same given name requires a chosen contact", () => {
  const [turn, earlyYes, picked] = conversation("A María por 20 euros, concepto regalo desde diaria", "sí", "María Vela");
  assert.deepEqual(turn.state.candidates.map(item => item.id), ["maria-uno", "maria-dos"]);
  assert.match(turn.message, /María Sierra o María Vela/u);
  assert.equal(turn.phraseId, "ambiguo-contacto");
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
  assert.equal(low.phraseId, "saldo-insuficiente");
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
  assert.equal(invalid.phraseId, "iban-invalido");
  assert.equal(transferSpeech(invalid.message, invalid.state, "es"), "Indica otro contacto o un IBAN válido.");
  const [reference] = conversation("A Ana, concepto sesión 42 desde diaria");
  assert.equal(reference.state.next, "amountCents");
  assert.equal(reference.state.slots.amountCents, undefined);
});

test("the Spanish and English summaries and repeated prompts abbreviate the spoken IBAN", () => {
  const grouped = "ES82 0000 0000 0000 0000 0000";
  const number = "ES8200000000000000000000";
  for (const [lang, command, confirm, ending] of [
    ["es", `A ${grouped} por 40 euros, concepto recibo ${grouped} desde diaria`, "sí", "la cuenta terminada en 0000"],
    ["en", `Send 40 euros to ${grouped} from current with reference receipt`, "yes", "the account ending in 0000"],
  ]) {
    const options = {...context, lang, allowConfirm: false};
    const draft = transferTurn(initialTransfer(), command, options);
    assert.equal(draft.state.phase, "ready");
    assert.equal(draft.state.slots.recipient.iban, number);
    const repeated = transferTurn(draft.state, confirm, options);
    assert.equal(repeated.message, draft.message);
    for (const turn of [draft, repeated]) {
      assert.equal(turn.phraseId, "confirmar");
      assert.ok(turn.message.includes(number));
      const spoken = transferSpeech(turn.message, turn.state, lang);
      assert.equal(spoken, turn.message.replaceAll(number, ending).replaceAll(grouped, ending));
      assert.ok(spoken.includes(ending));
    }
  }
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



test("only final, cited structured fields can populate the draft", () => {
  const raw = "Doce y medio para la destinataria habitual";
  const interpretation = {
    raw_transcript: raw,
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


test("collects an amount introduced by de before the recipient", () => {
  const [turn] = conversation("Haz una transferencia de 50 euros a Marta");
  assert.equal(turn.state.slots.amountCents, 5000);
  assert.equal(turn.state.slots.recipient.id, "marta");
});

test("collects an amount in a request to send money", () => {
  const people = {...context, contacts: [...context.contacts, {id: "pablo", name: "Pablo León"}]};
  const turn = transferTurn(initialTransfer(), "mándale 20 euros a Pablo", people);
  assert.equal(turn.state.slots.amountCents, 2000);
  assert.equal(turn.state.slots.recipient.id, "pablo");
});

test("keeps the amount while asking which contact with the same name", () => {
  const [turn] = conversation("quiero enviar 12,5 euros a María");
  assert.equal(turn.state.slots.amountCents, 1250);
  assert.equal(turn.state.candidates.length, 2);
});

test("por followed by a purpose is a reference", () => {
  const [turn] = conversation("Haz una transferencia de 50 euros a Marta por el alquiler");
  assert.equal(turn.state.slots.amountCents, 5000);
  assert.equal(turn.state.slots.concept, "el alquiler");
});

test("para followed by a purpose preserves the selected recipient", () => {
  const [before, turn] = conversation("A Marta por 50 euros", "para la cena");
  assert.deepEqual(turn.state.slots.recipient, before.state.slots.recipient);
  assert.equal(turn.state.slots.concept, "la cena");
});

test("preserves the content after el concepto es", () => {
  const [, turn] = conversation("A Marta por 50 euros", "el concepto es Entradas de cine");
  assert.equal(turn.state.slots.concept, "Entradas de cine");
});

test("accepts a grouped IBAN introduced with esta cuenta", () => {
  const [turn] = conversation("Transfiere 50 euros a esta cuenta ES82 0000 0000 0000 0000 0000");
  assert.equal(turn.state.slots.recipient.iban, "ES8200000000000000000000");
  assert.equal(turn.state.slots.amountCents, 5000);
});

test("accepts a spoken fractional amount after a recipient", () => {
  const [turn] = conversation("Transfiere a Marta cuarenta y cinco euros con cincuenta");
  assert.equal(turn.state.slots.recipient.id, "marta");
  assert.equal(turn.state.slots.amountCents, 4550);
});

for (const [phrase, id] of [["Lozano", "lozano"], ["la de Ortega", "ortega"], ["la segunda", "lozano"]]) {
  test("disambiguates the candidates with " + phrase, () => {
    const people = {...context, contacts: [
      {id: "ortega", name: "María Ortega Ruiz"}, {id: "lozano", name: "María Lozano Pérez"},
    ]};
    const state = transferTurn(initialTransfer(), "Quiero enviar 12,5 euros a María", people).state;
    const turn = transferTurn(state, phrase, people);
    assert.equal(turn.state.slots.recipient.id, id);
    assert.equal(turn.state.slots.amountCents, 1250);
  });
}

function finalResult(text, fields, {changed = Object.keys(fields), missing = [], ambiguous = []} = {}) {
  return {raw_transcript: text, is_final: true, fields, changed, missing, ambiguous};
}

function cited(value, quote) {
  return {value, quote, validation: "valid"};
}

test("a final cited interpretation is authoritative instead of consulting the local parser", () => {
  const text = "A Marta por 50 euros, concepto cena desde diaria";
  const interpretation = finalResult(text, {
    destination_contact_id: cited("ana", "Marta"),
    amount_cents: cited(6000, "50 euros"),
    concept: cited("referencia normalizada", "cena"),
  }, {missing: ["source_account_id"]});
  const turn = transferTurn(initialTransfer(), text, {...context, interpretation});
  assert.deepEqual(turn.state.slots, {
    recipient: {id: "ana", name: "Ana Prado"}, amountCents: 6000, concept: "referencia normalizada",
  });
  assert.equal(turn.state.next, "source");
});

test("an empty final interpretation leaves local-looking fields unassigned", () => {
  const text = "Haz una transferencia a Marta por 50 euros";
  const turn = transferTurn(initialTransfer(), text, {...context, interpretation: finalResult(text, {})});
  assert.deepEqual(turn.state.slots, {});
  assert.equal(turn.state.next, "recipient");
});

test("missing fields from a turn preserve previous values unless explicitly changed", () => {
  const [before] = conversation(complete);
  const text = "Cambia el concepto";
  const turn = transferTurn(before.state, text, {...context, interpretation: finalResult(text, {},
    {missing: ["amount_cents", "concept", "source_account_id"], changed: ["concept"]}),
  });
  assert.equal(turn.state.slots.amountCents, 4000);
  assert.equal(turn.state.slots.source, "daily");
  assert.equal(turn.state.slots.concept, undefined);
  assert.equal(turn.state.next, "concept");
});

test("structured ambiguity replaces the old destination and supports selecting either kind of candidate", () => {
  const [before] = conversation(complete);
  const text = "¿A Ana o al IBAN ES82 0000 0000 0000 0000 0000?";
  const number = "ES8200000000000000000000";
  const ambiguous = [
    {field: "destination_contact_id", candidates: ["ana", "unknown"]},
    {field: "destination_iban", candidates: [number]},
  ];
  const turn = transferTurn(before.state, text, {...context, interpretation: finalResult(text, {}, {ambiguous})});
  assert.equal(turn.state.slots.recipient, undefined);
  assert.deepEqual(turn.state.candidates.map(item => item.id || item.iban), ["ana", number]);
  const missingChoice = transferTurn(turn.state, "unknown", {...context, recipientChoice: "unknown"});
  for (const prompt of [turn, missingChoice]) {
    assert.equal(prompt.phraseId, "ambiguo-contacto");
    assert.equal(prompt.message, `¿Te refieres a Ana Prado o ${number}?`);
    assert.equal(transferSpeech(prompt.message, prompt.state, "es"), "¿Te refieres a Ana Prado o la cuenta terminada en 0000?");
  }
  assert.equal(transferTurn(turn.state, "sí", context).action, undefined);
  const chosen = transferTurn(turn.state, number, {...context, recipientChoice: number});
  assert.equal(chosen.state.phase, "ready");
  assert.equal(chosen.state.slots.recipient.iban, number);
  assert.equal(chosen.action, undefined);
});

test("an ambiguous amount without candidates clears a previously collected amount", () => {
  const [before] = conversation(complete);
  const text = "Dos euros y pico";
  const interpretation = finalResult(text, {}, {ambiguous: [{field: "amount_cents", candidates: []}]});
  const turn = transferTurn(before.state, text, {...context, interpretation});
  assert.equal(turn.state.slots.amountCents, undefined);
  assert.equal(turn.state.next, "amountCents");
  assert.equal(transferTurn(turn.state, "sí", context).action, undefined);
});

test("common transcription formats keep the correct amounts and ask about the two Marías", () => {
  const people = {...context, contacts: [...context.contacts, {id: "javier", name: "Javier Navarro"}]};
  const turn = transferTurn(initialTransfer(),
    "Haz una transferencia de 40 euros a Javier Navarro con el concepto CENA, desde la cuenta diaria.", people);
  assert.equal(turn.state.slots.amountCents, 4000);
  assert.equal(turn.state.slots.recipient.id, "javier");
  assert.equal(turn.state.slots.concept, "CENA");
  assert.equal(parseAmount("20 euros"), 2000);
  assert.equal(parseAmount("35 EUROS"), 3500);
  const grouped = transferTurn(initialTransfer(), "Transfiere 50.000 euros a Javier Navarro", people);
  assert.equal(grouped.state.slots.amountCents, 5000000);
  const [ambiguous] = conversation("Envia 15 euros a María con el concepto Entradas, desde la cuenta diaria.");
  assert.equal(ambiguous.state.slots.amountCents, 1500);
  assert.equal(ambiguous.state.candidates.length, 2);
  assert.equal(ambiguous.state.slots.concept, "Entradas");
});

for (const transcriptionProvider of ["Boltagon · GPU 1 · large-v3-turbo", "Funes / Talos (reserva)"]) {
  test(`transcription from ${transcriptionProvider} keeps its source and gives final text to dictation`, async ({mock}) => {
    const text = "A Marta";
    const final = {...finalResult(text, {destination_contact_id: cited("marta", "Marta")}),
      version: "cyrano.dictation/v0", dictation_route: "app", dictation_name: "Boltagon's Hoard"};
    const requests = [];
    mock.method(globalThis, "fetch", async (url, options) => {
      requests.push({url, body: options.body});
      return Response.json(url.endsWith("/understand") ? final : {text, provider: transcriptionProvider});
    });
    const clip = new Blob(["synthetic"], {type: "audio/wav"});
    const options = {state: initialTransfer(), context, locale: "es-ES", signal: new AbortController().signal, dictation: true};
    const partial = await transcribeTransferSpeech(clip, {...options, partial: true});
    assert.deepEqual(partial, {text, provider: "shared", transcriptionProvider});
    assert.equal(requests.length, 1);
    const reply = await transcribeTransferSpeech(clip, {...options, partial: false});
    assert.equal(reply.text, text);
    assert.equal(reply.provider, "shared");
    assert.equal(reply.transcriptionProvider, transcriptionProvider);
    assert.deepEqual(reply.interpretation, final);
    assert.ok(reply.transcriptionMs >= 0 && reply.understandingMs >= 0);
    const transcription = new URL(requests[1].url, "http://127.0.0.1");
    assert.match(transcription.pathname, /\/transcribe$/u);
    assert.match(transcription.searchParams.get("initial_prompt"), /Cuenta diaria.*Marta Vidal/u);
    assert.deepEqual(JSON.parse(requests[2].body).vocabulary.slice(0, 2), ["Cuenta diaria", "Ahorro"]);
    assert.equal(JSON.parse(requests[2].body).text, text);
  });
}

test("disabled or unavailable shared voice leaves the reply in writing", async ({mock}) => {
  let status = 409;
  const requests = [];
  mock.method(globalThis, "fetch", async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return Response.json({}, {status});
  });
  const events = [];
  const [review] = conversation(complete);
  for (status of [409, 503]) {
    await speakTransferReply(review.phraseId, {
      locale: "es-ES", signal: new AbortController().signal,
      onFallback: () => events.push("written"), onStart: () => events.push("voice"),
    });
  }
  assert.deepEqual(events, ["written", "written"]);
  assert.deepEqual(requests, Array(2).fill({phrase_id: "confirmar", language: "es"}));
});
