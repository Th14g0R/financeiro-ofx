(() => {
  const form = document.getElementById('duplicate-bulk-form');
  if (!form) return;

  const checkboxes = Array.from(document.querySelectorAll('.duplicate-review-checkbox[form="duplicate-bulk-form"]:not(:disabled)'));
  const selectedCount = document.getElementById('selected-review-count');
  const selectPageButton = document.getElementById('select-page-reviews');
  const clearButton = document.getElementById('clear-review-selection');
  const applyAllFiltered = document.getElementById('apply-all-filtered');
  const submitButton = document.getElementById('apply-bulk-review');
  const actionSelect = document.getElementById('bulk-action');
  const filteredCount = Number(form.dataset.filteredCount || 0);

  function countSelected() {
    return checkboxes.filter((checkbox) => checkbox.checked).length;
  }

  function updateState() {
    const count = countSelected();
    if (selectedCount) selectedCount.textContent = String(count);
    if (submitButton) {
      if (applyAllFiltered?.checked) {
        submitButton.textContent = `Aplicar aos ${filteredCount} grupos filtrados`;
      } else {
        submitButton.textContent = count === 1 ? 'Aplicar ao grupo selecionado' : `Aplicar aos ${count} grupos selecionados`;
      }
    }
  }

  checkboxes.forEach((checkbox) => checkbox.addEventListener('change', updateState));

  selectPageButton?.addEventListener('click', () => {
    checkboxes.forEach((checkbox) => { checkbox.checked = true; });
    updateState();
  });

  clearButton?.addEventListener('click', () => {
    checkboxes.forEach((checkbox) => { checkbox.checked = false; });
    if (applyAllFiltered) applyAllFiltered.checked = false;
    updateState();
  });

  applyAllFiltered?.addEventListener('change', updateState);

  form.addEventListener('submit', (event) => {
    const allFiltered = Boolean(applyAllFiltered?.checked);
    const count = countSelected();
    if (!allFiltered && count === 0) {
      event.preventDefault();
      window.alert('Selecione ao menos um grupo ou marque a opção para aplicar a todos os grupos filtrados.');
      return;
    }

    const actionText = actionSelect?.selectedOptions?.[0]?.textContent?.trim() || 'a decisão selecionada';
    const targetText = allFiltered
      ? `${filteredCount} grupo(s) do filtro atual`
      : `${count} grupo(s) selecionado(s)`;
    const confirmed = window.confirm(
      `Confirmar “${actionText}” para ${targetText}?\n\n` +
      'Cada movimentação será processada uma única vez dentro do grupo. Grupos incompatíveis com a ação escolhida serão preservados para revisão individual.'
    );
    if (!confirmed) {
      event.preventDefault();
      return;
    }

    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = 'Aplicando...';
    }
  });

  updateState();
})();
