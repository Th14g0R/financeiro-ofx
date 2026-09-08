(() => {
  "use strict";

  const CONNECTOR_ID = 200;

  function statusElement() {
    return document.getElementById("pluggyConnectStatus");
  }

  function setStatus(message, kind = "secondary") {
    const element = statusElement();

    if (!element) {
      return;
    }

    element.className = `small mt-3 text-${kind}`;
    element.textContent = message;
  }

  function csrfToken() {
    const form = document.getElementById("pluggyConnectCsrfForm");

    if (!form) {
      return "";
    }

    const input = form.querySelector(
      'input[name="csrfmiddlewaretoken"]'
    );

    return input ? input.value : "";
  }

  async function readJson(response) {
    try {
      return await response.json();
    } catch (_error) {
      return {};
    }
  }

  async function requestConnectToken(button) {
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrfToken());

    const itemPk = button.dataset.itemPk || "";

    if (itemPk) {
      body.append("item_pk", itemPk);
    }

    const response = await fetch(
      button.dataset.tokenUrl,
      {
        method: "POST",
        credentials: "same-origin",
        body,
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      }
    );

    const payload = await readJson(response);

    if (!response.ok) {
      throw new Error(
        payload.error
        || "Não foi possível obter o Connect Token."
      );
    }

    return payload;
  }

  async function captureItem(button, itemId) {
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrfToken());
    body.append("item_id", itemId);

    const response = await fetch(
      button.dataset.captureUrl,
      {
        method: "POST",
        credentials: "same-origin",
        body,
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      }
    );

    const payload = await readJson(response);

    if (!response.ok) {
      throw new Error(
        payload.error
        || "O Item foi criado, mas não pôde ser registrado."
      );
    }

    return payload;
  }

  async function openConnect(button) {
    if (
      typeof window.PluggyConnect
      !== "function"
    ) {
      throw new Error(
        "O componente oficial Pluggy Connect não foi carregado."
      );
    }

    setStatus(
      "Preparando autorização segura com o Meu Pluggy...",
      "primary"
    );

    const tokenData = await requestConnectToken(button);

    const config = {
      connectToken: tokenData.accessToken,
      includeSandbox: false,
      connectorIds: [CONNECTOR_ID],
      selectedConnectorId: CONNECTOR_ID,
      language: "pt",
      theme: "light",
      onSuccess: async (itemData) => {
        const itemId = (
          itemData
          && itemData.item
          && itemData.item.id
        )
          || (
            itemData
            && itemData.id
          )
          || "";

        if (!itemId) {
          setStatus(
            "A Pluggy concluiu a autorização, mas não retornou o Item ID.",
            "danger"
          );
          return;
        }

        try {
          setStatus(
            "Autorização concluída. Registrando a conexão no Financeiro...",
            "primary"
          );

          await captureItem(
            button,
            itemId
          );

          setStatus(
            "Conexão registrada. Atualizando a página...",
            "success"
          );

          window.setTimeout(
            () => window.location.reload(),
            700
          );
        } catch (error) {
          setStatus(
            error.message
            || "Falha ao registrar a conexão.",
            "danger"
          );
        }
      },
      onError: (error) => {
        const message = (
          error
          && error.message
        )
          ? error.message
          : "A Pluggy informou falha na autorização.";

        setStatus(
          `Falha na autorização: ${message}`,
          "danger"
        );
      },
      onClose: () => {
        if (
          statusElement()
          && !statusElement().classList.contains("text-success")
          && !statusElement().classList.contains("text-danger")
        ) {
          setStatus(
            "Janela do Meu Pluggy fechada.",
            "secondary"
          );
        }
      },
    };

    const updateItem = (
      tokenData.updateItem
      || button.dataset.itemId
      || ""
    );

    if (updateItem) {
      config.updateItem = updateItem;
    }

    const connect = new window.PluggyConnect(
      config
    );

    await connect.init();
  }

  document.addEventListener(
    "DOMContentLoaded",
    () => {
      const buttons = document.querySelectorAll(
        ".pluggy-connect-button"
      );

      buttons.forEach((button) => {
        button.addEventListener(
          "click",
          async () => {
            if (button.disabled) {
              return;
            }

            button.disabled = true;

            try {
              await openConnect(button);
            } catch (error) {
              setStatus(
                error.message
                || "Não foi possível abrir o Meu Pluggy.",
                "danger"
              );
            } finally {
              button.disabled = false;
            }
          }
        );
      });
    }
  );
})();
