/** @odoo-module **/
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";

class RealtimeDatetime extends Component {
    static template = "z_project.RealtimeDatetime";
    static props = standardFieldProps;

    setup() {
        this.state = useState({ now: new Date() });
        onMounted(() => {
            this.interval = setInterval(() => {
                this.state.now = new Date(); // updated every 1 second
            }, 1000);
        });
        onWillUnmount(() => {
            clearInterval(this.interval);
        });
    }

    get displayValue() {
        const startStr = document.querySelector('div[name="z_time_start"] span')?.textContent.trim();
        if (startStr) {
            const [datePart, timePart] = startStr.split(" ");
            const [month, day, year] = datePart.split("/").map(Number);
            const [hours, minutes, seconds] = timePart.split(":").map(Number);
            const start = new Date(year, month - 1, day, hours, minutes, seconds);
            const now = this.state.now;
            const diffSec = Math.floor((now - start) / 1000);
            const totalHours = Math.floor(diffSec / 3600);
            const mins = String(Math.floor((diffSec % 3600) / 60)).padStart(2, "0");
            const secs = String(diffSec % 60).padStart(2, "0");
            const totalHoursStr = String(totalHours).padStart(2, "0");
            return `${totalHoursStr}:${mins}:${secs}`;
        }
        // fallback
        const d = this.state.now;
        const pad = (n) => (n < 10 ? "0" + n : n);
        return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }
}

registry.category("fields").add("RealtimeDatetime", {
    component: RealtimeDatetime,
});
