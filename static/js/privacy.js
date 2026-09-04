(function () {
    const STORAGE_KEY = "financeiroOfx.hideSensitiveValues";

    function getButton() {
        return document.getElementById("toggleSensitiveValues");
    }

    function setHidden(hidden) {
        document.documentElement.classList.toggle(
            "values-hidden",
            hidden
        );

        document
            .querySelectorAll("[data-sensitive-value]")
            .forEach((element) => {
                if (!element.dataset.originalValue) {
                    element.dataset.originalValue =
                        element.textContent.trim();
                }

                element.textContent = hidden
                    ? "••••••"
                    : element.dataset.originalValue;
            });

        const button = getButton();

        if (button) {
            button.textContent = hidden
                ? "Mostrar valores"
                : "Ocultar valores";

            button.setAttribute(
                "aria-pressed",
                hidden ? "true" : "false"
            );
        }

        window.localStorage.setItem(
            STORAGE_KEY,
            hidden ? "1" : "0"
        );
    }

    document.addEventListener("DOMContentLoaded", () => {
        const hidden =
            window.localStorage.getItem(STORAGE_KEY) === "1";

        setHidden(hidden);

        const button = getButton();

        if (button) {
            button.addEventListener("click", () => {
                const currentlyHidden =
                    document.documentElement.classList.contains(
                        "values-hidden"
                    );

                setHidden(!currentlyHidden);
            });
        }
    });
})();
