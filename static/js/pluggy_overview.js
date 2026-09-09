(() => {
  "use strict";

  const forms = document.querySelectorAll("form[data-loading-form]");

  for (const form of forms) {
    form.addEventListener("submit", (event) => {
      // Preserve the exact submit button that triggered the request before
      // disabling controls. Disabled controls are not submitted with the
      // form, so the old implementation could drop name="action" when
      // the first decision button was clicked.
      const submitter = event.submitter;
      if (submitter && submitter.name) {
        const previous = form.querySelector('input[data-loading-submitter="true"]');
        if (previous) {
          previous.remove();
        }

        const hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = submitter.name;
        hidden.value = submitter.value;
        hidden.dataset.loadingSubmitter = "true";
        form.appendChild(hidden);
      }

      const buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
      for (const button of buttons) {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
      }

      if (submitter && submitter.tagName === "BUTTON") {
        submitter.dataset.originalText = submitter.textContent.trim();
        submitter.textContent = form.dataset.loadingText || "Processando...";
      } else if (submitter && submitter.tagName === "INPUT") {
        submitter.dataset.originalText = submitter.value;
        submitter.value = form.dataset.loadingText || "Processando...";
      }
    });
  }
})();
