import assert from "node:assert/strict";
import test from "node:test";
import { prepareProjectCreation, projectCreationError } from "./src/pages/projectCreation.js";

const base = { name: "Turnos", description: "", template: "booking" };
const limits = { min: 1, max: 2 };
const option = { key: 4, title: " Riego ", category: " Huerto ", description: " " };

test("a starter without item requirements keeps the basic creation payload", () => {
  const inventory = { ...base, template: "inventory" };
  assert.deepEqual(prepareProjectCreation(inventory, undefined, [option], true), { body: inventory });
});

test("booking options are trimmed, get unique identifiers and omit empty descriptions", () => {
  assert.deepEqual(prepareProjectCreation(base, limits, [option, { ...option, key: 9, description: " Tarde " }], true), {
    body: { ...base, items: [
      { id: "option-1", title: "Riego", category: "Huerto" },
      { id: "option-2", title: "Riego", category: "Huerto", description: "Tarde" },
    ] },
  });
});

test("the form blocks empty or excess options and focuses the missing field", () => {
  assert.equal(prepareProjectCreation(base, limits, [], true).error, "Añade entre 1 y 2 opciones de reserva.");
  assert.equal(prepareProjectCreation(base, limits, [option, option, option], false).error,
    "Add between 1 and 2 booking options.");
  assert.deepEqual(prepareProjectCreation(base, limits, [{ ...option, title: " " }], true), {
    error: "Escribe un nombre para la opción de reserva 1.", field: "booking-4-title",
  });
  assert.deepEqual(prepareProjectCreation(base, limits, [option, { ...option, key: 9, category: "" }], false), {
    error: "Enter a category for booking option 2.", field: "booking-9-category",
  });
});

test("creation errors keep the localized server message or name the field from validation", () => {
  assert.equal(projectCreationError({ code: "project_creation_input", message: "Añade una opción." }, true), "Añade una opción.");
  assert.equal(projectCreationError({ code: "invalid_arguments", issues: [{ loc: "name", msg: "Field required" }] }, true),
    "Escribe un nombre para la aplicación.");
  assert.equal(projectCreationError({ code: "invalid_arguments", issues: [{ loc: "items.0" }] }, false),
    "Check the booking options.");
  assert.match(projectCreationError(new Error("Unexpected English response"), true), /^No se pudo crear/u);
});
