const copy = {
  es: {
    language: 'Idioma', catalogue: 'Catálogo', category: 'Categoría', all: 'Todas las categorías',
    reservation: 'Solicitar una reserva', item: 'Elemento', date: 'Fecha', dateFormat: 'dd/mm/aaaa', name: 'Nombre',
    dateError: 'Escribe una fecha válida con el formato dd/mm/aaaa.',
    emailError: 'Escribe un correo electrónico válido.', requiredError: 'Completa los campos obligatorios.',
    email: 'Correo electrónico', submit: 'Enviar solicitud', sending: 'Enviando…',
    success: 'Solicitud recibida. Referencia', failure: 'No se ha podido enviar la solicitud. Inténtalo de nuevo.',
    preview: 'El envío está disponible en la web publicada.',
    results: (count) => count === 1 ? '1 elemento visible' : `${count} elementos visibles`,
  },
  en: {
    language: 'Language', catalogue: 'Catalogue', category: 'Category', all: 'All categories',
    reservation: 'Request a booking', item: 'Item', date: 'Date', dateFormat: 'mm/dd/yyyy', name: 'Name',
    dateError: 'Enter a valid date in mm/dd/yyyy format.',
    emailError: 'Enter a valid email address.', requiredError: 'Complete the required fields.',
    email: 'Email address', submit: 'Send request', sending: 'Sending…',
    success: 'Request received. Reference', failure: 'The request could not be sent. Try again.',
    preview: 'Submissions are available on the published website.',
    results: (count) => count === 1 ? '1 visible item' : `${count} visible items`,
  },
};

const site = JSON.parse(document.querySelector('#catalogue-data').textContent);
const filter = document.querySelector('#category');
const catalogue = document.querySelector('#catalogue');
const form = document.querySelector('#reservation');
const itemInput = form.elements.namedItem('item');
const dateInput = form.elements.namedItem('date');
const submit = form.querySelector('button');
const confirmation = document.querySelector('#confirmation');
const languages = document.querySelector('.languages');
const categories = new Map(site.items.map(({category}) => [JSON.stringify(category), category]));
let language = site.lang;
let status = '';
let reference = '';
let invalidControl = null;

form.noValidate = true;

function showStatus() {
  confirmation.textContent = status === 'success'
    ? `${copy[language].success} ${reference}`
    : copy[language][status] || '';
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function showCatalogue() {
  const visible = site.items.filter(({category}) => !filter.value || JSON.stringify(category) === filter.value);
  catalogue.replaceChildren(...visible.map((item) => {
    const row = element('li', '', '');
    const details = element('div', '', '');
    details.append(element('h3', item.title[language]));
    if (item.description[language]) details.append(element('p', item.description[language]));
    row.append(element('span', item.category[language], 'category'), details);
    return row;
  }));
  document.querySelector('#results').textContent = filter.value ? copy[language].results(visible.length) : '';
}

function readDate(value, lang) {
  const match = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(value.trim());
  if (!match) return '';
  const [, first, second, year] = match;
  const [day, month] = (lang === 'es' ? [first, second] : [second, first]).map((part) => part.padStart(2, '0'));
  const iso = `${year}-${month}-${day}`;
  const date = new Date(iso + 'T00:00:00Z');
  return year !== '0000' && !Number.isNaN(date.getTime()) && date.toISOString().startsWith(iso) ? iso : '';
}

function clearInvalid() {
  if (!invalidControl) return;
  invalidControl.removeAttribute('aria-invalid');
  invalidControl.removeAttribute('aria-describedby');
  invalidControl = null;
  status = '';
}

function showInvalid(control, message) {
  invalidControl = control;
  control.setAttribute('aria-invalid', 'true');
  control.setAttribute('aria-describedby', confirmation.id);
  status = message;
  showStatus();
  control.focus();
}

function translate(next) {
  const date = readDate(dateInput.value, language);
  if (date && language !== next) {
    const [year, month, day] = date.split('-');
    dateInput.value = (next === 'es' ? [day, month, year] : [month, day, year]).join('/');
  }
  language = next;
  document.documentElement.lang = next;
  for (const node of document.querySelectorAll('[data-label]')) node.textContent = copy[next][node.dataset.label];
  languages.setAttribute('aria-label', copy[next].language);
  for (const button of languages.querySelectorAll('button')) button.setAttribute('aria-pressed', button.dataset.language === next);
  const description = document.querySelector('#description');
  description.textContent = site.description[next];
  description.hidden = !site.description[next];
  const category = filter.value;
  const item = itemInput.value;
  dateInput.placeholder = copy[next].dateFormat;
  filter.replaceChildren(new Option(copy[next].all, ''), ...Array.from(categories, ([key, value]) => new Option(value[next], key)));
  filter.value = category;
  itemInput.replaceChildren(...site.items.map(({id, title}) => new Option(title[next], id)));
  if (item) itemInput.value = item;
  if (submit.disabled) submit.textContent = copy[next].sending;
  showCatalogue();
  showStatus();
}

languages.addEventListener('click', (event) => {
  if (event.target.dataset.language) translate(event.target.dataset.language);
});
filter.addEventListener('change', showCatalogue);
form.addEventListener('input', (event) => {
  if (event.target === invalidControl) {
    clearInvalid();
    showStatus();
  }
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (submit.disabled) return;
  clearInvalid();
  const invalid = form.querySelector('input:invalid, select:invalid');
  if (invalid) {
    showInvalid(invalid, invalid.validity.typeMismatch ? 'emailError' : 'requiredError');
    return;
  }
  const date = readDate(dateInput.value, language);
  if (!date) {
    showInvalid(dateInput, 'dateError');
    return;
  }
  const fields = Object.fromEntries(new FormData(form));
  fields.date = date;
  submit.disabled = true;
  submit.textContent = copy[language].sending;
  status = '';
  showStatus();
  try {
    const response = await fetch(form.action, {
      method: form.method,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(fields),
    });
    const result = await response.json();
    if (response.status === 404) status = 'preview';
    else if (response.ok && typeof result.reference === 'string') {
      reference = result.reference;
      status = 'success';
      form.reset();
    } else status = 'failure';
  } catch {
    status = 'failure';
  } finally {
    submit.disabled = false;
    submit.textContent = copy[language].submit;
    showStatus();
  }
});
translate(language);
