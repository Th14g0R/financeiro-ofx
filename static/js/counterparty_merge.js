"use strict";

(function () {
    const selectAll =
        document.getElementById(
            "counterpartySelectAll"
        );
    const mergeButton =
        document.getElementById(
            "counterpartyMergeButton"
        );
    const selectedCount =
        document.getElementById(
            "counterpartySelectedCount"
        );
    const checkboxes = Array.from(
        document.querySelectorAll(
            ".counterparty-select"
        )
    );

    if (
        !mergeButton
        || !selectedCount
        || !checkboxes.length
    ) {
        return;
    }

    function refreshState() {
        const selected = checkboxes.filter(
            (checkbox) => checkbox.checked
        ).length;

        selectedCount.textContent =
            String(selected);
        mergeButton.disabled =
            selected < 2;

        if (selectAll) {
            selectAll.checked =
                selected === checkboxes.length;
            selectAll.indeterminate =
                selected > 0
                && selected < checkboxes.length;
        }
    }

    checkboxes.forEach(
        (checkbox) => {
            checkbox.addEventListener(
                "change",
                refreshState
            );
        }
    );

    if (selectAll) {
        selectAll.addEventListener(
            "change",
            function () {
                checkboxes.forEach(
                    (checkbox) => {
                        checkbox.checked =
                            selectAll.checked;
                    }
                );
                refreshState();
            }
        );
    }

    refreshState();
})();
