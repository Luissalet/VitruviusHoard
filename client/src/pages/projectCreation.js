export function prepareProjectCreation(base, limits, options, es) {
  if (!limits) return { body: base };
  if (options.length < limits.min || options.length > limits.max) {
    return { error: es
      ? `Añade entre ${limits.min} y ${limits.max} opciones de reserva.`
      : `Add between ${limits.min} and ${limits.max} booking options.` };
  }
  const items = [];
  for (const [index, option] of options.entries()) {
    const title = option.title.trim();
    const category = option.category.trim();
    if (!title) return {
      error: es ? `Escribe un nombre para la opción de reserva ${index + 1}.`
        : `Enter a name for booking option ${index + 1}.`,
      field: `booking-${option.key}-title`,
    };
    if (!category) return {
      error: es ? `Escribe una categoría para la opción de reserva ${index + 1}.`
        : `Enter a category for booking option ${index + 1}.`,
      field: `booking-${option.key}-category`,
    };
    const description = option.description.trim();
    items.push({ id: `option-${index + 1}`, title, category, ...(description && { description }) });
  }
  return { body: { ...base, items } };
}

export function projectCreationError(error, es) {
  if (error.code === "project_creation_input") return error.message;
  const field = error.issues?.[0]?.loc?.split(".")[0];
  if (field === "name") return es ? "Escribe un nombre para la aplicación." : "Enter a name for the application.";
  if (field === "items") return es ? "Revisa las opciones de reserva." : "Check the booking options.";
  if (field === "template") return es ? "Elige un punto de partida de la lista." : "Choose a starting point from the list.";
  return es ? "No se pudo crear la aplicación. Revisa los datos e inténtalo de nuevo."
    : "Could not create the application. Check the details and try again.";
}
