(() => {
  "use strict";

  const forms = document.querySelectorAll("form[data-loading-form]");

  for (const form of forms) {
    form.addEventListener("submit", () => {
      const button = form.querySelector('button[type="submit"]');
      if (!button || button.disabled) {
        return;
      }

      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.dataset.originalText = button.textContent.trim();
      button.textContent = form.dataset.loadingText || "Processando...";
    });
  }
})();
