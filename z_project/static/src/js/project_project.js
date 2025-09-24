/** @odoo-module */
$(document).ready(function() {
    // onchange group type project
    // impact to hide show in project and non project
    const groupSelect = $('select[name="z_group_type_project"]');
    const projectDiv = $('#z_type_in_project');
    const nonProjectDiv = $('#z_type_non_project');
    const typeInProjectSelect = projectDiv.find('select[name="z_type_in_project"]');
    const typeNonProjectSelect = nonProjectDiv.find('select[name="z_type_non_project"]');
    // This function runs on initial page load and onchange
    function checkVisibility(clearValue = false) {
        const groupType = groupSelect.val();
        // Hide both divs
        projectDiv.hide();
        nonProjectDiv.hide();
        if (groupType === 'project') {
            projectDiv.show();
            // Only clear the value if the user triggered the change
            if (clearValue) {
                typeInProjectSelect.val('');
            }
        } else if (groupType === 'non_project') {
            nonProjectDiv.show();
            // Only clear the value if the user triggered the change
            if (clearValue) {
                typeNonProjectSelect.val('');
            }
        }
    }
    // Call the function on initial page load with clearValue = false
    checkVisibility(false);
    // Call the function on change event with clearValue = true
    groupSelect.on('change', function() {
        checkVisibility(true);
    });
    // dropdown group by
    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll('[data-bs-toggle="collapse"]').forEach(function (btn) {
            let target = document.querySelector(btn.getAttribute("data-bs-target"));
            if (target) {
                target.addEventListener("shown.bs.collapse", function () {
                    btn.querySelector(".fa").classList.remove("fa-caret-right");
                    btn.querySelector(".fa").classList.add("fa-caret-down");
                });
                target.addEventListener("hidden.bs.collapse", function () {
                    btn.querySelector(".fa").classList.remove("fa-caret-down");
                    btn.querySelector(".fa").classList.add("fa-caret-right");
                });
            }
        });
    });
});

// library accounting format
$(document).ready(function() {
    function formatAccounting(input) {
        let value = input.val();
        let cleanedValue = value.replace(/[^0-9.]/g, '');
        let parts = cleanedValue.split('.');
        let integerPart = parts[0];
        let decimalPart = parts[1] ? '.' + parts[1].slice(0, 2) : '';
        integerPart = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        input.val(integerPart + decimalPart);
    }
    $('.js-accounting-format').each(function() {
        formatAccounting($(this));
    });
    $('.js-accounting-format').on('blur', function() {
        formatAccounting($(this));
    });
    $('form').on('submit', function() {
        $('.js-accounting-format').each(function() {
            let unformattedValue = $(this).val().replace(/,/g, '');
            $(this).val(unformattedValue);
        });
    });
});

