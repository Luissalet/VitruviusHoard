(() => {
  const locale = document.documentElement.lang || "es-ES";
  const spanish = /^es(?:-|$)/i.test(locale);
  const labels = spanish ? {
    year: "aaaa", month: "mm", day: "dd", required: "Completa este campo.",
    date: "Introduce una fecha válida.", time: "Introduce una hora válida.",
    range: "Elige un valor dentro del intervalo permitido.",
    calendar: "Calendario", clock: "Reloj",
  } : {
    year: "yyyy", month: "mm", day: "dd", required: "Complete this field.",
    date: "Enter a valid date.", time: "Enter a valid time.",
    range: "Choose a value within the permitted range.",
    calendar: "Calendar", clock: "Clock",
  };

  const dateOptions = {
    year: "numeric", month: "2-digit", day: "2-digit",
    timeZone: "UTC", calendar: "gregory", numberingSystem: "latn",
  };
  let formatter;
  try {
    formatter = new Intl.DateTimeFormat(locale === "en" ? "en-GB" : locale, dateOptions);
  } catch {
    formatter = new Intl.DateTimeFormat("es-ES", dateOptions);
  }
  const parts = formatter.formatToParts(new Date("2006-11-23T00:00:00Z"));
  const order = parts.filter((part) => part.type !== "literal").map((part) => part.type);
  const dateHint = parts.map((part) => labels[part.type] || part.value).join("");

  function validCalendarDate(value) {
    if (value.startsWith("0000")) return "";
    const date = new Date(value + "T00:00:00Z");
    return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value ? value : "";
  }

  function isoDate(value) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return validCalendarDate(value);
    const digits = /^\d{8}$/.test(value);
    const separated = value.match(/^(\d{1,4})[/. -](\d{1,2})[/. -](\d{1,4})$/);
    if (!digits && !separated) return "";
    const chunks = separated?.slice(1) || [];
    let cursor = 0;
    const fields = {};
    for (const [index, name] of order.entries()) {
      const length = name === "year" ? 4 : 2;
      fields[name] = digits ? value.slice(cursor, cursor + length) : chunks[index];
      cursor += length;
    }
    if (fields.year.length !== 4 || fields.month.length > 2 || fields.day.length > 2) return "";
    return validCalendarDate([fields.year, fields.month.padStart(2, "0"), fields.day.padStart(2, "0")].join("-"));
  }

  function isoTime(value) {
    if (/^\d{4}$/.test(value)) value = value.slice(0, 2) + ":" + value.slice(2);
    const parts = value.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
    if (!parts || +parts[1] > 23 || +parts[2] > 59 || +(parts[3] || 0) > 59) return "";
    return parts[1].padStart(2, "0") + ":" + parts[2] + (parts[3] ? ":" + parts[3] : "");
  }

  function enhance(native) {
    if (!native.id || native.readOnly || native.disabled || native.closest("[data-native-picker]")) return;
    const field = native.parentElement;
    const isDate = native.type === "date";
    const originalId = native.id;
    const input = document.createElement("input");
    const error = document.createElement("p");
    const hasPicker = typeof native.showPicker === "function";
    const display = (value) => {
      if (!value || !isDate) return value;
      const date = new Date(value + "T00:00:00Z");
      return Number.isNaN(date.valueOf()) ? "" : formatter.format(date);
    };

    input.type = "text";
    input.id = originalId;
    input.className = "design-temporal-text";
    input.inputMode = "numeric";
    input.autocomplete = "off";
    input.placeholder = isDate ? dateHint : "hh:mm";
    input.required = native.required;
    input.defaultValue = display(native.defaultValue);
    input.value = display(native.value);
    for (const attribute of ["aria-label", "aria-labelledby"]) {
      if (native.hasAttribute(attribute)) input.setAttribute(attribute, native.getAttribute(attribute));
    }

    error.id = originalId + "-error";
    error.className = "design-error";
    error.setAttribute("role", "alert");
    error.hidden = true;
    input.setAttribute("aria-describedby", [native.getAttribute("aria-describedby"), error.id].filter(Boolean).join(" "));
    native.id = originalId + "-native";
    native.required = false;
    native.tabIndex = -1;
    native.classList.add("design-native-picker");
    native.setAttribute("aria-hidden", "true");
    field.dataset.enhanced = "";
    field.append(input);
    field.after(error);
    let committedValue = native.value;

    function reflect(message) {
      input.setCustomValidity(message);
      const invalid = Boolean(message);
      error.textContent = message;
      error.hidden = !invalid;
      if (invalid) input.setAttribute("aria-invalid", "true");
      else input.removeAttribute("aria-invalid");
    }

    function sync(commit) {
      const raw = input.value.trim();
      const previous = native.value;
      native.value = isDate ? isoDate(raw) : isoTime(raw);
      let message = "";
      if (raw && !native.value) message = isDate ? labels.date : labels.time;
      else if (raw && !native.validity.valid) message = labels.range;
      else if (!raw && input.required) message = labels.required;
      if (message) native.value = "";
      input.setCustomValidity(message);
      if (commit || !error.hidden) reflect(message);
      if (commit && !message) input.value = display(native.value);
      if (native.value !== previous) native.dispatchEvent(new Event("input", { bubbles: true }));
      if (commit && !message && native.value !== committedValue) {
        committedValue = native.value;
        native.dispatchEvent(new Event("change", { bubbles: true }));
      }
      return !message;
    }

    input.addEventListener("input", () => sync(false));
    input.addEventListener("change", (event) => {
      event.stopPropagation();
      sync(true);
    });
    input.addEventListener("blur", () => sync(true));
    input.addEventListener("invalid", () => sync(true));
    native.addEventListener("change", () => {
      committedValue = native.value;
      input.value = display(native.value);
      sync(true);
    });
    native.form?.addEventListener("reset", (event) => {
      // Read the field after the browser restores its default value.
      setTimeout(() => {
        if (event.defaultPrevented) return;
        committedValue = native.value;
        input.value = display(native.value);
        reflect("");
        sync(false);
      }, 0);
    });

    sync(false);
    if (hasPicker) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "design-picker";
      button.textContent = isDate ? labels.calendar : labels.clock;
      button.addEventListener("click", () => {
        try {
          native.showPicker();
        } catch {
          input.focus();
        }
      });
      field.append(button);
    }
  }

  function init() {
    document.querySelectorAll(".design-temporal > input:is([type=date], [type=time])").forEach(enhance);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
