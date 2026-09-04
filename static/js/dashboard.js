"use strict";

(function () {
    function decodeData(value) {
        if (!value) {
            return {};
        }

        const normalized = value
            .replace(/-/g, "+")
            .replace(/_/g, "/");

        const padding =
            "=".repeat(
                (4 - normalized.length % 4) % 4
            );

        const binary = atob(
            normalized + padding
        );
        const bytes = Uint8Array.from(
            binary,
            (character) =>
                character.charCodeAt(0)
        );

        return JSON.parse(
            new TextDecoder("utf-8").decode(
                bytes
            )
        );
    }

    const dataElement =
        document.getElementById(
            "dashboardData"
        );

    if (!dataElement || typeof Chart === "undefined") {
        return;
    }

    const periodData = decodeData(
        dataElement.dataset.periodChart
    );
    const expenseData = decodeData(
        dataElement.dataset.expenseChart
    );

    const currencyFormatter =
        new Intl.NumberFormat(
            "pt-BR",
            {
                style: "currency",
                currency: "BRL"
            }
        );

    const periodCanvas =
        document.getElementById(
            "periodMovementChart"
        );

    if (periodCanvas) {
        const drilldownUrls =
            Array.isArray(
                periodData.drilldown_urls
            )
                ? periodData.drilldown_urls
                : [];

        const hasDrilldown =
            drilldownUrls.length > 0;

        if (hasDrilldown) {
            periodCanvas.style.cursor =
                "pointer";
        }

        new Chart(
            periodCanvas,
            {
                type: "bar",
                data: {
                    labels:
                        periodData.labels
                        || [],
                    datasets: [
                        {
                            label: "Entradas externas",
                            data:
                                periodData.credits
                                || [],
                            backgroundColor:
                                "rgba(25, 135, 84, 0.65)",
                            borderColor:
                                "rgb(25, 135, 84)",
                            borderWidth: 1
                        },
                        {
                            label: "Saídas externas",
                            data:
                                periodData.debits
                                || [],
                            backgroundColor:
                                "rgba(220, 53, 69, 0.65)",
                            borderColor:
                                "rgb(220, 53, 69)",
                            borderWidth: 1
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio:
                        false,
                    interaction: {
                        mode: "index",
                        intersect: false
                    },
                    onClick(
                        event,
                        elements
                    ) {
                        if (
                            !hasDrilldown
                            || !elements
                            || !elements.length
                        ) {
                            return;
                        }

                        const index =
                            elements[0].index;
                        const url =
                            drilldownUrls[index];

                        if (url) {
                            window.location.href =
                                url;
                        }
                    },
                    plugins: {
                        legend: {
                            position: "bottom"
                        },
                        tooltip: {
                            callbacks: {
                                label(context) {
                                    return (
                                        context.dataset.label
                                        + ": "
                                        + currencyFormatter.format(
                                            context.parsed.y
                                        )
                                    );
                                },
                                footer(items) {
                                    if (
                                        hasDrilldown
                                        && items.length
                                    ) {
                                        return (
                                            "Clique para abrir este mês"
                                        );
                                    }

                                    return "";
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback(value) {
                                    return (
                                        currencyFormatter.format(
                                            value
                                        )
                                    );
                                }
                            }
                        }
                    }
                }
            }
        );
    }

    const expenseCanvas =
        document.getElementById(
            "expenseChart"
        );

    if (
        expenseCanvas
        && Array.isArray(
            expenseData.values
        )
        && expenseData.values.length
    ) {
        new Chart(
            expenseCanvas,
            {
                type: "doughnut",
                data: {
                    labels:
                        expenseData.labels
                        || [],
                    datasets: [
                        {
                            data:
                                expenseData.values
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio:
                        false,
                    plugins: {
                        legend: {
                            position: "bottom"
                        },
                        tooltip: {
                            callbacks: {
                                label(context) {
                                    return (
                                        context.label
                                        + ": "
                                        + currencyFormatter.format(
                                            context.parsed
                                        )
                                    );
                                }
                            }
                        }
                    }
                }
            }
        );
    }
})();
