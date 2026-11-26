const SLOTS = ["recipient", "amountCents", "concept", "source"];

const COPY = {
  es: {
    start: "¿A quién quieres hacer la transferencia?",
    recipient: "¿A quién quieres hacer la transferencia?",
    amountCents: "¿Qué importe quieres transferir?",
    concept: "¿Qué concepto quieres indicar?",
    source: "¿Desde qué cuenta quieres transferir?",
    ambiguous: names => "¿A cuál te refieres? " + names.join(" o ") + ".",
    unknownRecipient: "No encuentro ese contacto. Indica otro nombre o un IBAN válido.",
    unknownSource: "No encuentro esa cuenta de origen.",
    badAmount: "Indica un importe mayor que cero, con un máximo de dos decimales.",
    insufficient: (account, balance) => "Saldo insuficiente en " + account + " (" + balance + "). Indica otro importe u otra cuenta.",
    summary: (amount, recipient, account, concept) => "Transferencia simulada de " + amount + " a " + recipient + " desde " + account + ", con el concepto «" + concept + "». ¿Confirmas la transferencia?",
    cancelled: "Transferencia cancelada.",
    completed: "La transferencia ya se ha realizado.",
  },
  en: {
    start: "Who would you like to transfer money to?",
    recipient: "Who would you like to transfer money to?",
    amountCents: "How much would you like to transfer?",
    concept: "What reference would you like to use?",
    source: "Which account should the money come from?",
    ambiguous: names => "Which one do you mean? " + names.join(" or ") + ".",
    unknownRecipient: "I couldn't find that contact. Enter another name or a valid IBAN.",
    unknownSource: "I couldn't find that source account.",
    badAmount: "Enter an amount greater than zero, with up to two decimal places.",
    insufficient: (account, balance) => "The balance in " + account + " (" + balance + ") is too low. Enter another amount or account.",
    summary: (amount, recipient, account, concept) => "Simulated transfer of " + amount + " to " + recipient + " from " + account + ", with the reference “" + concept + "”. Confirm the transfer?",
    cancelled: "Transfer cancelled.",
    completed: "The transfer has already been completed.",
  },
};

const NUMBERS = {
  cero: 0, uno: 1, un: 1, una: 1, dos: 2, tres: 3, cuatro: 4, cinco: 5, seis: 6, siete: 7, ocho: 8, nueve: 9,
  diez: 10, once: 11, doce: 12, trece: 13, catorce: 14, quince: 15, dieciseis: 16, diecisiete: 17,
  dieciocho: 18, diecinueve: 19, veinte: 20, veintiuno: 21, veintiun: 21, veintidos: 22, veintitres: 23,
  veinticuatro: 24, veinticinco: 25, veintiseis: 26, veintisiete: 27, veintiocho: 28, veintinueve: 29,
  treinta: 30, cuarenta: 40, cincuenta: 50, sesenta: 60, setenta: 70, ochenta: 80, noventa: 90,
  cien: 100, ciento: 100, doscientos: 200, trescientos: 300, cuatrocientos: 400, quinientos: 500,
  seiscientos: 600, setecientos: 700, ochocientos: 800, novecientos: 900,
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9,
  ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17,
  eighteen: 18, nineteen: 19, twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70,
  eighty: 80, ninety: 90,
};

function normal(text) {
  return text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().trim();
}

function clean(text) {
  return text.trim().replace(/^[\s,;:«“"']+|[\s,;:!?¿¡.«»“”"']+$/gu, "");
}

function wordNumber(text) {
  const tokens = text.split(/[\s-]+/u);
  let total = 0;
  let part = 0;
  let previous = Infinity;
  let seen = false;
  for (const token of tokens) {
    if (token === "y" || token === "and") continue;
    const value = Object.hasOwn(NUMBERS, token) ? NUMBERS[token] : undefined;
    if (token === "mil" || token === "thousand") {
      if (total) return null;
      total = (part || 1) * 1000;
      part = 0;
      previous = Infinity;
    } else if (token === "hundred" && part >= 1 && part <= 9) {
      part *= 100;
      previous = part;
    } else if (value !== undefined && (previous === Infinity || value < previous && previous >= 20 && value < (previous >= 100 ? 100 : 10))) {
      part += value;
      previous = value;
    } else {
      return null;
    }
    seen = true;
  }
  return seen ? total + part : null;
}

export function parseAmount(text, lang = "es") {
  const groups = lang === "en" ? "," : ".";
  const decimals = lang === "en" ? "." : ",";
  const amount = normal(text).replace(/^€\s*/u, "").replace(/\s*(?:€|euros?)$/u, "");
  const mark = decimals === "." ? "\\." : ",";
  const group = groups === "." ? "\\." : ",";
  const digitMatch = amount.match(new RegExp("^(\\d+|\\d{1,3}(?:" + group + "\\d{3})+)(?:" + mark + "(\\d{1,2}))?$", "u"));
  let cents;
  if (digitMatch) {
    cents = Number(digitMatch[1].replaceAll(groups, "")) * 100 + Number((digitMatch[2] || "").padEnd(2, "0"));
  } else {
    const spoken = amount.match(/^(.+?)\s+(?:euros?\s+(?:con|y|and)|con|coma|point)\s+(.+?)(?:\s+(?:centimos?|cents?))?$/u);
    if (spoken) {
      const whole = /^\d+$/u.test(spoken[1]) ? Number(spoken[1]) : wordNumber(spoken[1]);
      const fraction = /^\d{1,2}$/u.test(spoken[2]) ? Number(spoken[2]) : wordNumber(spoken[2]);
      if (whole !== null && fraction !== null && fraction < 100) {
        const decimal = /\s(?:coma|point)\s/u.test(amount);
        cents = whole * 100 + (decimal && fraction < 10 && !/^0/u.test(spoken[2]) ? fraction * 10 : fraction);
      }
    } else {
      const whole = wordNumber(amount);
      if (whole !== null) cents = whole * 100;
    }
  }
  return Number.isSafeInteger(cents) && cents > 0 ? cents : null;
}

function iban(text) {
  const value = text.replace(/\s|-/gu, "").toUpperCase();
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/u.test(value) || value.startsWith("ES") && !/^ES\d{22}$/u.test(value)) return null;
  let remainder = 0;
  for (const char of value.slice(4) + value.slice(0, 4)) {
    remainder = /\d/u.test(char) ? (remainder * 10 + Number(char)) % 97 : (remainder * 100 + char.charCodeAt(0) - 55) % 97;
  }
  return remainder === 1 ? value : null;
}

function lookup(list, text) {
  const key = normal(text);
  if (!key) return [];
  const exact = list.filter(item => [item.id, item.name, ...(item.aliases || [])].some(name => normal(name) === key));
  if (exact.length) return exact;
  return list.filter(item => [item.name, ...(item.aliases || [])].some(name => normal(name).startsWith(key + " ")));
}

function asRecipient(text, contacts) {
  const candidates = lookup(contacts, text);
  if (candidates.length === 1) return {id: candidates[0].id, name: candidates[0].name};
  if (candidates.length > 1) return {candidates};
  const number = iban(text);
  return number ? {iban: number, name: number} : null;
}

// Markers are kept separate from slot values. In particular, digits in a name,
// a reference or an IBAN never become a transfer amount.
const MARKERS = {
  es: {
    source: "(?:desde|con cargo a|origen\\s*[:=])",
    concept: "(?:con (?:el |este )?concepto|concepto\\s*[:=]?)",
    recipient: "(?:(?:destinatari[oa]|beneficiari[oa])\\s*[:=]|(?:para|a)(?!\\s+(?:la\\s+)?cuenta\\s+de\\s+origen\\b))",
    amountCents: "(?:por|importe\\s*[:=])",
  },
  en: {
    source: "(?:from|source\\s*[:=])",
    concept: "(?:with (?:the )?(?:reference|memo)|(?:reference|memo)\\s*[:=]?)",
    recipient: "(?:(?:recipient|beneficiary)\\s*[:=]|to)",
    amountCents: "(?:for|amount\\s*[:=])",
  },
};
const REPAIR = /^(?:(?:no|s[ií]|yes)[,\s]+)?(?:mejor|cambia (?:a|el importe a)|actually|instead|make it|change (?:it|the amount) to)\s+/iu;
const REQUEST = /^(?:(?:por favor|please)[,\s]+)?(?:(?:haz|quiero hacer|hacer|ordena|prepara)(?:\s+una)?\s+transferencia|(?:make|start|prepare)(?:\s+a)?\s+transfer|transfi[eé]re(?:me|le)?|transferir|env[ií]a(?:le)?|p[aá]sa(?:le)?|(?:send|transfer|pay))\b[,\s]*/iu;
const CONFIRM = /^(?:s[ií](?:[,\s]+confirmo)?|confirm[ao](?: la transferencia)?|confirmar(?: la transferencia)?|adelante|yes(?:[,\s]+confirm)?|(?:i )?confirm(?: the transfer)?|go ahead)[.!]?$/iu;
const CANCEL = /^(?:cancela(?:r)?(?: la transferencia)?|anula(?:r)?(?: la transferencia)?|olvida(?:r)?(?: la transferencia|lo)?|no confirmo|no|cancel(?: the transfer)?|never mind|do not confirm)[.!]?$/iu;

export function isTransferCommand(text) {
  const raw = text.trim();
  return CONFIRM.test(raw) || CANCEL.test(raw);
}

function interpretedSlots(raw, interpretation, contacts) {
  if (interpretation?.is_final !== true) return {};
  const {fields, changed, ambiguous} = interpretation;
  function evidenced(name, type) {
    const field = fields?.[name];
    if (Array.isArray(changed) && !changed.includes(name)) return;
    if (field?.validation === "valid" && typeof field.value === type
        && typeof field.quote === "string" && field.quote.trim() && raw.includes(field.quote)) return field.value;
  }
  const id = evidenced("destination_contact_id", "string");
  const wireIban = evidenced("destination_iban", "string");
  const amountCents = evidenced("amount_cents", "number");
  const dest = ambiguous?.find(item => item.field === "destination_contact_id");
  return {
    recipient: id && contacts.some(item => item.id === id) ? id : wireIban,
    amountCents: Number.isSafeInteger(amountCents) && amountCents > 0 ? amountCents : undefined,
    source: evidenced("source_account_id", "string"),
    concept: evidenced("concept", "string"),
    candidates: Array.isArray(dest?.candidates) ? contacts.filter(item => dest.candidates.includes(item.id)) : [],
  };
}

function splitSlots(raw, lang, expected) {
  const markers = MARKERS[lang];
  const source = raw.replace(REQUEST, "").replace(REPAIR, "");
  const pattern = "(?:^|[\\s;,:])(?:" + Object.entries(markers).map(([key, marker]) => "(?<" + key + ">" + marker + ")").join("|") + ")\\s+";
  const matches = [...source.matchAll(new RegExp(pattern, "giu"))];
  if (expected === "concept" && source === raw && matches[0]?.index !== 0) {
    return {slots: {concept: raw}, head: "", repaired: false};
  }
  const slots = {};
  let head = clean(source.slice(0, matches[0]?.index ?? source.length));
  for (let index = 0; index < matches.length; index++) {
    const match = matches[index];
    const field = SLOTS.find(key => match.groups[key] !== undefined);
    let value = clean(source.slice(match.index + match[0].length, matches[index + 1]?.index ?? source.length));
    if (field === "recipient") {
      // «a Marta no, a María» reassigns the slot on the later marker.
      if (/\s+(?:no|not)$/iu.test(value) && matches[index + 1]?.groups.recipient) continue;
      // Accept «a Ana 40 euros» with the amount after a name.
      if (lang === "es") value = value.replace(/^(?:la )?cuenta(?: con IBAN)?\s+/iu, "");
      const adjacent = value.match(/^(.+?)\s+(\d[\d.,]*\s*(?:€|euros?)|[\p{L}\s-]+\s+euros?)$/iu);
      if (adjacent && !iban(value)) {
        const words = value.match(/\S+/gu);
        for (let split = 1; split < words.length; split++) {
          const amount = words.slice(split).join(" ");
          if (parseAmount(amount, lang) !== null) {
            slots.amountCents = amount;
            value = words.slice(0, split).join(" ").replace(/\s+de$/iu, "");
            break;
          }
        }
      }
    }
    if (field === "source") value = value.replace(/^(?:(?:mi|la|my|the)\s+)?(?:cuenta|account)\s+/iu, "");
    if (field === "concept") {
      // Keep the literal reference, including ordinary words such as «a».
      const end = matches.find((later, position) => position > index && later.groups.source);
      value = clean(source.slice(match.index + match[0].length, end?.index ?? source.length));
      slots.concept = value.replace(/^(?:(?:de|of)\s+)?[:=]\s*/u, "");
      if (!end) break;
      index = matches.indexOf(end) - 1;
      continue;
    }
    slots[field] = value;
  }
  if (head && parseAmount(head, lang) !== null) {
    slots.amountCents ??= head;
    head = "";
  }
  return {slots, head, repaired: REPAIR.test(raw)};
}

export function initialTransfer() {
  return {slots: {}, candidates: [], phase: "collecting", next: "recipient"};
}

export function transferTurn(state, text, {contacts, accounts, lang = "es", allowConfirm = true, interpretation}) {
  lang = lang === "en" ? "en" : "es";
  const copy = COPY[lang];
  const raw = text.trim();
  if (state.phase === "executing") return {state};
  if (CANCEL.test(raw)) {
    if (state.phase === "complete") return {state, message: copy.completed};
    return {state: {...initialTransfer(), phase: "cancelled"}, message: copy.cancelled};
  }

  if (CONFIRM.test(raw)) {
    if (state.phase === "ready" && allowConfirm) return {state: {...state, phase: "executing"}, action: {...state.slots}};
    if (state.phase === "ready") return {state, message: state.summary};
    return {state, message: copy[state.next] || copy.start};
  }

  const next = state.phase === "cancelled" || state.phase === "complete" ? initialTransfer() : state;
  const slots = {...next.slots};
  const parsed = splitSlots(raw, lang, next.next);
  const changes = parsed.slots;
  const understood = interpretedSlots(raw, interpretation, contacts);
  if (parsed.head) {
    const head = parsed.head.replace(/^(?:(?:la|mi|the|my)\s+)?(?:cuenta|account)\s+/iu, "");
    const account = lookup(accounts, head);
    const recipient = asRecipient(parsed.head, next.candidates.length ? next.candidates : contacts);
    if (parsed.repaired && /^(?:[+\-€]?\d)|\b(?:euros?|centimos|cents)\b/u.test(normal(head))) {
      changes.amountCents ??= parsed.head;
    } else if (parsed.repaired && recipient) changes.recipient ??= parsed.head;
    else if (parsed.repaired && account.length === 1) changes.source ??= head;
    else if (!Object.keys(changes).length) changes[next.next || "recipient"] = head;
    else if (recipient) changes.recipient ??= parsed.head;
  }

  // The shared parser can supply a cited value when this utterance didn't
  // resolve locally. Every returned value still goes through the slot checks.
  let candidates = next.candidates;
  let issue;
  if (understood.source && lookup(accounts, changes.source || "").length !== 1) changes.source = understood.source;
  if (understood.concept && !changes.concept) changes.concept = understood.concept;
  if (understood.amountCents && parseAmount(changes.amountCents || "", lang) === null) changes.amountCents = understood.amountCents;
  if (Object.hasOwn(changes, "recipient") || understood.recipient || understood.candidates?.length) {
    const local = Object.hasOwn(changes, "recipient") ? asRecipient(changes.recipient, contacts) : null;
    const proposed = understood.recipient ? asRecipient(understood.recipient, contacts) : null;
    const recipient = local || (understood.candidates?.length > 1 ? {candidates: understood.candidates} : proposed);
    candidates = recipient?.candidates ?? [];
    if (recipient && !candidates.length) slots.recipient = recipient;
    else {
      delete slots.recipient;
      if (!candidates.length) issue = ["recipient", copy.unknownRecipient];
    }
  }
  if (Object.hasOwn(changes, "amountCents")) {
    const amount = typeof changes.amountCents === "number" ? changes.amountCents : parseAmount(changes.amountCents, lang);
    if (amount === null) {
      delete slots.amountCents;
      issue ??= ["amountCents", copy.badAmount];
    } else slots.amountCents = amount;
  }
  if (Object.hasOwn(changes, "concept")) {
    const concept = clean(changes.concept);
    if (concept && concept.length <= 140) slots.concept = concept;
    else delete slots.concept;
  }
  if (Object.hasOwn(changes, "source")) {
    const matches = lookup(accounts, changes.source);
    if (matches.length === 1) slots.source = matches[0].id;
    else {
      delete slots.source;
      issue ??= ["source", copy.unknownSource];
    }
  }

  const progress = {slots, candidates, phase: "collecting", next: null};
  if (candidates.length) {
    return {state: {...progress, next: "recipient"}, message: copy.ambiguous(candidates.map(item => item.name))};
  }
  const missing = SLOTS.find(key => slots[key] === undefined);
  if (missing) return {state: {...progress, next: missing}, message: issue?.[0] === missing ? issue[1] : copy[missing]};

  const account = accounts.find(item => item.id === slots.source);
  if (!account) {
    delete slots.source;
    return {state: {...progress, next: "source"}, message: copy.unknownSource};
  }
  const currency = new Intl.NumberFormat(lang === "es" ? "es-ES" : "en-IE", {style: "currency", currency: "EUR", useGrouping: "always"});
  if (Number.isSafeInteger(account.balanceCents) && account.balanceCents < slots.amountCents) {
    return {state: {...progress, phase: "insufficient", next: "amountCents"}, message: copy.insufficient(account.name, currency.format(account.balanceCents / 100))};
  }
  const summary = copy.summary(currency.format(slots.amountCents / 100), slots.recipient.name, account.name, slots.concept);
  return {state: {...progress, phase: "ready", summary}, message: summary};
}
