from odoo import api, fields, models, _
from datetime import datetime, date, timedelta, timezone
from odoo.exceptions import ValidationError
from odoo.tools.translate import _
from html import unescape
import time
import re


class ProjectTask(models.Model):
    _inherit = "project.task"

    def _reindex_subtasks(self):
        for idx, child in enumerate(self.child_ids.sorted("create_date"), start=1):
            child.name = f"{self.name}.{str(idx).zfill(2)}"
            child._reindex_subtasks()

    def get_all_subtasks_inclusive(self):
        """Helper untuk ambil task + semua subtasks (recursive)."""
        self.ensure_one()
        all_tasks = self
        if self.child_ids:
            for child in self.child_ids:
                all_tasks |= child.get_all_subtasks_inclusive()
        return all_tasks

    @api.depends(
        'timesheet_ids.z_timesheet_start_date',
        'timesheet_ids.z_timesheet_end_date',
        'child_ids.z_actual_start_date',
        'child_ids.z_actual_end_date'
    )
    def _compute_actual_dates(self):
        for task in self:
            all_tasks = task.get_all_subtasks_inclusive()
            all_lines = all_tasks.mapped("timesheet_ids")
            start_dates = [d for d in all_lines.mapped("z_timesheet_start_date") if d]
            end_dates = [d for d in all_lines.mapped("z_timesheet_end_date") if d]
            task.z_actual_start_date = min(start_dates) if start_dates else False
            task.z_actual_end_date = max(end_dates) if end_dates else False

    @api.depends('z_project_task_state', 'child_ids.z_progress_project')
    def _compute_progress(self):
        """
        Hitung progress berdasarkan status done atau progress anak-anaknya.
        """
        for task in self:
            if task.child_ids:
                total_children = len(task.child_ids)
                if total_children == 0:
                    task.z_progress_project = 0
                    continue
                total_progress = sum(child.z_progress_project for child in task.child_ids)
                task.z_progress_project = total_progress / total_children
            else:
                if task.z_project_task_state == 'done':
                    task.z_progress_project = 100
                else:
                    task.z_progress_project = 0

    @api.depends(
        'project_id.z_mandays_budget',
        'project_id.task_ids',
        'parent_id.z_mandays_budget',
        'parent_id.child_ids',
    )
    def _getMandaysBudget(self):
        for this in self:
            mandays = this.project_id.z_mandays_budget or 0
            clean_mandays = mandays
            if clean_mandays and this.parent_id.child_ids:
                mandays = this.parent_id.z_mandays_budget or 0
                clean_mandays = mandays / len(this.parent_id.child_ids)
            elif clean_mandays and this.project_id.task_ids:
                clean_mandays = mandays / len(this.project_id.task_ids.filtered(lambda x: not x.parent_id))
            this.z_mandays_budget = clean_mandays

    @api.depends(
        'timesheet_ids.unit_amount',
        'child_ids.timesheet_ids.unit_amount'
    )
    def _getActualMandaysBudget(self):
        for this in self:
            # self task and all subtask
            all_tasks = this.get_all_subtasks_inclusive()
            actual_mandays = len(all_tasks.mapped('timesheet_ids').filtered(
                lambda x: x.z_timesheet_start_date and x.z_timesheet_end_date))
            this.z_actual_budget_mandays = actual_mandays

    @api.depends('child_ids')
    def _getSubtaskCount(self):
        for this in self:
            task_done = len(this.child_ids.filtered(lambda x: x.z_project_task_state == 'done'))
            this.z_subtask_done_count = task_done / len(this.child_ids) * 100 if task_done and this.child_ids else 0
            this.z_subtask_count = len(this.child_ids)

    @api.depends('timesheet_ids')
    def _getTimesheetCount(self):
        for this in self:
            timesheet_done = len(this.timesheet_ids.filtered(lambda x: x.z_state == 'approved'))
            this.z_timesheet_done_count = timesheet_done / len(
                this.timesheet_ids) * 100 if timesheet_done and this.timesheet_ids else 0
            this.z_timesheet_count = len(this.timesheet_ids)

    @api.depends(
        'project_id.task_ids',
        'parent_id.child_ids',
    )
    def _getBobot(self):
        for this in self:
            bobot = 100
            clean_bobot = bobot
            if this.parent_id.child_ids:
                bobot = this.parent_id.z_bobot
                clean_bobot = bobot / len(this.parent_id.child_ids)
            elif this.project_id.task_ids:
                clean_bobot = bobot / len(this.project_id.task_ids.filtered(lambda x: not x.parent_id))
            this.z_bobot = clean_bobot

    def _compute_running_duration(self):
        for this in self:
            this.z_running_duration = "00:00:00"
            if this.z_time_start:
                start = fields.Datetime.from_string(this.z_time_start).replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                delta = now - start
                total_seconds = int(delta.total_seconds())
                total_hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                this.z_running_duration = f"{total_hours:02}:{minutes:02}:{seconds:02}"

    def _getTimeStart(self):
        for this in self:
            time_start = False
            employee_ids = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.user.id)], limit=1)
            if employee_ids:
                timesheet_ids = this.timesheet_ids.filtered(
                    lambda x: x.employee_id.id == employee_ids.id and not x.z_timesheet_end_date)
                if timesheet_ids:
                    time_start = timesheet_ids.z_timesheet_start_date
            this.z_time_start = time_start

    @api.depends('project_id.label_tasks')
    def _compute_name_of_project(self):
        """Get name of project from project.label_tasks"""
        for task in self:
            task.z_name_of_project = task.project_id.label_tasks if task.project_id else ''

    @api.depends('project_id.z_type_in_project')
    def _compute_project_type_visibility(self):
        """Determine if maintenance fields should be visible"""
        for task in self:
            task.z_is_maintenance = (task.project_id.z_type_in_project == 'maintenance') if task.project_id else False

    # override
    name = fields.Char("Title", required=False)
    project_id = fields.Many2one('project.project', string='Projects',
                                 domain="['|', ('company_id', '=', False), ('company_id', '=?',  company_id)]",
                                 compute="_compute_project_id", store=True, precompute=True, recursive=True,
                                 readonly=False, index=True, tracking=True, change_default=True)
    date_deadline = fields.Datetime(string='Deadline Date', index=True, tracking=True)
    # added
    z_bobot = fields.Float(string="Bobot (%)", compute=_getBobot, store=True, digits=(12, 2))
    z_value_project = fields.Float(string="Value Project (Budget)")
    z_regional_id = fields.Many2one('area.regional', string='Regional')
    z_technology_id = fields.Many2one('technology.used', string='Technology')
    z_severity_id = fields.Many2one('severity.master', string='Severity')
    z_mandays_budget = fields.Float(string="Budget Mandays", compute=_getMandaysBudget, store=True)
    z_actual_budget_mandays = fields.Float(string="Actual Mandays", compute=_getActualMandaysBudget, store=True)
    z_progress_project = fields.Float(string="Progress", compute="_compute_progress", store=True, digits=(12, 2))
    z_quality_entry = fields.Float(string="Quality (%)")
    z_master_task_id = fields.Many2one('task.master', string='Name of The Tasks')
    z_head_assignes_ids = fields.Many2many(comodel_name="hr.employee", relation="task_head_employee_rel",
                                           column2="employee_id", string="Head Assignees")
    z_member_assignes_ids = fields.Many2many(comodel_name="hr.employee", relation="task_member_employee_rel",
                                             column1="task_id", column2="employee_id", string="Member Assignees")
    z_project_task_state = fields.Selection([
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('approved1', 'The First Approved'),
        ('approved2', 'The Second Approved'),
        ('done', 'Done'),
        ('reject', 'Rejected'),
        ('cancel', 'Cancelled'),
    ], string='Status', default="new")
    z_project_type = fields.Selection(related="project_id.z_type_in_project", string="Type Of Project", store=True,
                                      readonly=True)
    z_planned_start_date = fields.Date(string='Planned Start Date')
    z_planned_end_date = fields.Date(string='Planned End Date')
    z_actual_start_date = fields.Date(string='Actual Start Date', compute="_compute_actual_dates", store=True)
    z_actual_end_date = fields.Date(string='Actual End Date', compute="_compute_actual_dates", store=True)
    z_invoice_plan_ids = fields.One2many('project.task.invoice.plan', 'z_invoce_plan_id', string='Invoice Plan')
    z_missing_from = fields.Char(string="Missing From", readonly=True,
                                 help="Menunjukkan task ini dibuat karena ada gap dari nomor tertentu.")
    z_description = fields.Char('Description')
    z_subtask_count = fields.Integer(string='Count', compute=_getSubtaskCount, store=False)
    z_subtask_done_count = fields.Integer(string='Done Percent', compute=_getSubtaskCount, store=False)
    z_timesheet_count = fields.Integer(string='Count', compute=_getTimesheetCount, store=False)
    z_timesheet_done_count = fields.Integer(string='Done Percent', compute=_getTimesheetCount, store=False)
    z_time_start = fields.Datetime(string="Time Start", compute=_getTimeStart, store=False)
    z_running_duration = fields.Char(string="Running Duration", compute=_compute_running_duration, store=False)
    z_name_of_project = fields.Char(string='Name of Project', compute='_compute_name_of_project', store=True,
                                    readonly=True)
    z_is_maintenance = fields.Boolean(string='Is Maintenance Project', compute='_compute_project_type_visibility',
                                      store=True)
    z_timer_attachment_ids = fields.Many2many('ir.attachment', 'task_timer_attachment_rel', 'task_id', 'attachment_id',
                                              string='Timer Attachments')

    # not used
    z_quality_calculation = fields.Float(string="Quality Calc (%)")
    z_time_end = fields.Datetime(string='Time End')

    @api.model
    def create(self, vals):
        task = super().create(vals)
        if task.parent_id:
            task.generate_sequence_name()
            task.parent_id.message_post(
                body=_("Subtask %s dibuat di bawah %s.") % (
                    task.display_name, task.parent_id.display_name
                )
            )
        else:
            task.generate_project_sequence_name()
        task._getMandaysBudget()
        task._getActualMandaysBudget()
        task._getBobot()
        return task

    def unlink(self):
        parents = self.mapped("parent_id")
        deleted_names = self.mapped("display_name")
        res = super().unlink()
        for parent in parents:
            parent.message_post(
                body=_("Subtask %s dihapus dari parent %s.") % (
                    ", ".join(deleted_names), parent.display_name
                )
            )
        return res

    def action_request_timesheet(self):
        employee_ids = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.user.id)], order='id desc',
                                                             limit=1)
        values = {
            'default_partner_id': self.partner_id.id,
            'default_project_id': self.project_id.id,
            'default_employee_id': employee_ids.id if employee_ids else False,
            'default_task_id': self.id,
            'default_company_id': self.env.user.company_id.id,
        }
        return {
            "name": _("Request Timesheet"),
            "type": "ir.actions.act_window",
            "res_model": "account.analytic.line",
            "view_mode": "form",
            "domain": [],
            "context": values,
            'views': [
                [self.env.ref('z_project.z_account_analytic_line_form').id, 'form'],
            ],
        }

    def action_create_subtask(self):
        self.env['project.task'].create({
            'parent_id': self.id,
            'partner_id': self.partner_id.id,
            'project_id': self.project_id.id,
            'z_head_assignes_ids': [(6, 0, self.z_head_assignes_ids.ids)],
            'z_member_assignes_ids': [(6, 0, self.z_member_assignes_ids.ids)],
            'tag_ids': [(6, 0, self.tag_ids.ids)],
            'z_planned_start_date': datetime.now(),
            'z_planned_end_date': datetime.now(),
            'date_deadline': datetime.now(),
        })
        self.action_view_tasks()

    def action_view_tasks(self):
        return {
            "name": _("Timesheet"),
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "view_mode": "list,form",
            "domain": [('id', 'in', self.child_ids.ids)],
            "context": {},
            'views': [
                [self.env.ref('z_project.z_project_task_list').id, 'list'],
                [self.env.ref('z_project.z_project_task_form_inherit_project').id, 'form'],
            ],
        }

    def action_view_timesheets(self):
        return {
            "name": _("Timesheet"),
            "type": "ir.actions.act_window",
            "res_model": "account.analytic.line",
            "view_mode": "list,form",
            "domain": [('id', 'in', self.timesheet_ids.ids)],
            "context": {},
            'views': [
                [self.env.ref('z_project.z_account_analytic_line_list').id, 'list'],
                [self.env.ref('z_project.z_account_analytic_line_form').id, 'form'],
            ],
        }

    def action_cancel(self):
        self.z_project_task_state = 'cancel'

    def action_set_to_draft(self):
        self.z_project_task_state = 'new'

    def action_start_timesheet(self):
        employee = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.user.id)], limit=1)
        if not employee:
            raise ValidationError('Kamu tidak masuk dalam data karyawan. Silahkan hubungi administrator.')

        # PATCH: Status otomatis ke in_progress
        if self.z_project_task_state == 'new':
            self.z_project_task_state = 'in_progress'

        timesheet = self.env['account.analytic.line'].sudo().search([
            ('id', 'in', self.timesheet_ids.ids),
            ('task_id', '=', self.id),
            ('employee_id', '=', employee.id),
            ('z_timesheet_end_date', '=', False)
        ], limit=1)
        if timesheet:
            raise ValidationError('Terdapat timesheet yang belum selesai.')

        self.action_timer_start()
        self.timesheet_ids = [(0, 0, {
            'date': datetime.now(),
            'z_timesheet_start_date': datetime.now(),
            'employee_id': employee.id,
            'z_is_paused': False,
        })]

    def action_end_timesheet(self):
        employee_ids = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.user.id)], limit=1)
        if not employee_ids:
            raise ValidationError('Kamu tidak masuk dalam data karyawan. Silahkan hubungi administrator.')
        timesheet_ids = self.env['account.analytic.line'].sudo().search(
            [('id', 'in', self.timesheet_ids.ids), ('employee_id', '=', employee_ids.id)], order='id desc', limit=1)
        if not timesheet_ids:
            raise ValidationError('Data timesheet tidak tersedia.')
        elif timesheet_ids.z_timesheet_end_date:
            raise ValidationError('Semua timesheet sudah selesai.')
        else:
            if not self.env.context.get('confirmTimeStop', False):
                return {
                    "name": _("Time Stop"),
                    "type": "ir.actions.act_window",
                    "res_model": "project.task",
                    "view_mode": "form",
                    "target": "new",
                    "res_id": self.id,
                    "domain": [],
                    "context": {},
                    'views': [
                        [self.env.ref('z_project.z_project_task_form_timer').id, 'form'],
                    ],
                }
            timesheet_ids.write({
                'z_timesheet_end_date': datetime.now(),
                'name': self.z_description,
                'z_state': 'approved',
                'z_is_paused': False,  # NEW: Reset pause state when ending
            })

    def action_finish_task(self):
        # validasi sub-task
        if self.child_ids.filtered(lambda x: x.z_project_task_state != 'done'):
            raise ValidationError('Masih terdapat Sub-Task yang belum selesai.')

        self.z_project_task_state = 'done'

    def generate_sequence_name(self):
        """Generate nama otomatis untuk subtask + deteksi gap"""
        if self.parent_id:
            siblings = self.parent_id.child_ids.filtered(lambda t: t.id != self.id)
            existing_numbers = []
            for sib in siblings:
                if sib.name and sib.name.startswith(self.parent_id.name + "."):
                    try:
                        num = int(sib.name.split(".")[-1])
                        existing_numbers.append(num)
                    except:
                        pass
            if existing_numbers:
                next_number = max(existing_numbers) + 1
                missing = set(range(1, next_number)) - set(existing_numbers)
                self.name = f"{self.parent_id.name}.{str(next_number).zfill(2)}"
                return min(missing) if missing else False
            else:
                self.name = f"{self.parent_id.name}.01"
                return False

    def generate_project_sequence_name(self):
        if self.project_id:
            siblings = self.project_id.task_ids.filtered(lambda t: not t.parent_id and t.id != self.id)
            existing_numbers = []
            for sib in siblings:
                if sib.name and sib.name.startswith("T-"):
                    try:
                        num = int(sib.name.split("-")[-1])
                        existing_numbers.append(num)
                    except:
                        pass
            if existing_numbers:
                next_number = max(existing_numbers) + 1
                missing = set(range(1, next_number)) - set(existing_numbers)
                self.name = f"T-{str(next_number).zfill(2)}"
                return min(missing) if missing else False
            else:
                self.name = "T-01"
                return False

    def action_view_subtask(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("project.project_task_action_sub_task")
        action["domain"] = [("parent_id", "=", self.id)]
        action["context"] = {
            "default_parent_id": self.id,
            "default_project_id": self.project_id.id,
            "group_by": "z_project_task_state",
        }
        return action


class AccountAnalyticLine(models.Model):
    _name = 'account.analytic.line'
    _inherit = ['account.analytic.line', 'mail.thread', 'mail.activity.mixin']

    @api.depends('z_timesheet_start_date', 'z_timesheet_end_date')
    def _compute_unit_amount(self):
        for line in self:
            if line.z_timesheet_start_date and line.z_timesheet_end_date:
                delta = line.z_timesheet_end_date - line.z_timesheet_start_date
                total_seconds = delta.total_seconds()
                if hasattr(line, 'z_pause_duration') and line.z_pause_duration:
                    total_seconds -= line.z_pause_duration
                line.unit_amount = round(total_seconds / 3600.0, 2)
            else:
                line.unit_amount = 0.0

    # override
    unit_amount = fields.Float(string='Time Spent (Hours)', compute="_compute_unit_amount", store=True, readonly=False,
                               digits=(12, 2))
    # added
    z_timesheet_start_date = fields.Datetime(string='Start Date')
    z_timesheet_end_date = fields.Datetime(string='End Date')
    z_timesheet_spent = fields.Float(string='Time Spent')
    z_line_ids = fields.One2many('account.analytic.line.request', 'z_timesheet_id', string='Lines')
    z_state = fields.Selection([
        ('waiting_approval', 'Waiting Approval'),
        ('approved', 'Approved'),
    ], string='Status', default='waiting_approval')
    z_is_paused = fields.Boolean(string='Timer Paused', default=False,
                                 help="Indicates if the timer is currently paused")
    z_pause_start_time = fields.Datetime(string='Pause Start Time', help="When the timer was last paused")
    z_pause_duration = fields.Float(string='Total Pause Duration (seconds)', default=0.0,
                                    help="Total time paused in seconds")
    z_pause_log = fields.Text(string='Pause Log', help="Log of all pause/resume actions")

    def action_approve(self):
        self.z_state = 'approved'

    def action_view(self):
        return {
            "name": _("Request Timesheet"),
            "type": "ir.actions.act_window",
            "res_model": "account.analytic.line",
            "view_mode": "form",
            "res_id": self.id,
            "domain": [],
            "context": {},
            'views': [
                [self.env.ref('z_project.z_account_analytic_line_form').id, 'form'],
            ],
        }

        # NEW: Pause/Resume methods

    def action_pause_timer(self):
        """Pause the timer and record pause start time"""
        self.ensure_one()
        if not self.z_is_paused:
            self.z_is_paused = True
            self.z_pause_start_time = fields.Datetime.now()

            # Log the pause action
            log_entry = f"Paused at {self.z_pause_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            self.z_pause_log = (self.z_pause_log or '') + log_entry

            return True
        return False

    def action_resume_timer(self):
        """Resume the timer and calculate pause duration"""
        self.ensure_one()
        if self.z_is_paused and self.z_pause_start_time:
            resume_time = fields.Datetime.now()
            pause_duration = (resume_time - self.z_pause_start_time).total_seconds()

            self.z_is_paused = False
            self.z_pause_duration += pause_duration

            # Log the resume action
            log_entry = f"Resumed at {resume_time.strftime('%Y-%m-%d %H:%M:%S')} (paused for {pause_duration:.1f}s)\n"
            self.z_pause_log = (self.z_pause_log or '') + log_entry

            self.z_pause_start_time = False
            return True
        return False

    def get_effective_duration(self):
        """Get the actual working duration excluding pause time"""
        self.ensure_one()
        if self.z_timesheet_start_date and self.z_timesheet_end_date:
            total_duration = (self.z_timesheet_end_date - self.z_timesheet_start_date).total_seconds()
            return total_duration - (self.z_pause_duration or 0)
        return 0


class AccountAnalyticLineRequest(models.Model):
    _name = "account.analytic.line.request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Request Timesheet"
    _rec_name = "z_name"
    _order = "id desc"

    @api.depends(
        'z_current_start_date',
        'z_current_end_date',
    )
    def _getCurrentTimeSpent(self):
        for this in self:
            time = 0
            if this.z_current_start_date and this.z_current_end_date:
                time = this.z_current_end_date - this.z_current_start_date
                time = time.total_seconds() / 3600
            this.z_current_time_spent = time

    z_timesheet_id = fields.Many2one('account.analytic.line', string='Timesheet', ondelete='cascade')
    z_employee_id = fields.Many2one('hr.employee', string='Employee')
    z_name = fields.Char(string='Description')
    z_current_start_date = fields.Datetime(string='Actual Start')
    z_current_end_date = fields.Datetime(string='Actual End')
    z_current_time_spent = fields.Float(string='Actual Spent', compute=_getCurrentTimeSpent, store=True)
    z_state = fields.Selection([
        ('waiting_approval', 'Waiting Approval'),
        ('approved', 'Approved'),
    ], string='Status', default='waiting_approval')
    # not used
    z_ori_start_date = fields.Datetime(string='Original Start Date')
    z_ori_end_date = fields.Datetime(string='Original End Date')
    z_ori_time_spent = fields.Float(string='Original Time Spent')

    def action_approve(self):
        self.z_state = 'approved'
        self.z_timesheet_id.write({
            'date': self.z_current_start_date.date(),
            'z_timesheet_start_date': self.z_current_start_date,
            'z_timesheet_end_date': self.z_current_end_date,
            'unit_amount': self.z_current_time_spent,
            'name': self.z_name,
        })


class ProjectTaskInvoicePlan(models.Model):
    _name = "project.task.invoice.plan"
    _description = "Invoice Plan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "z_name"
    _order = "id desc"

    z_invoce_plan_id = fields.Many2one('project.task', string='Project', ondelete='cascade')
    z_name = fields.Char(string='Invoice Description')
    z_number_of_invoice = fields.Char(string='No. Invoice')
    z_invoice_date = fields.Date(string='Invoice Date')
    z_amount_total = fields.Float(string='Amount Total', digits=(12, 2), required=True)
    z_state = fields.Char(string='Status')
