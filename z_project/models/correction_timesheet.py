from odoo import api, fields, models, _


class CorrectionTimesheet(models.Model):

    _name = "correction.timesheet"
    _description = "Correction Timesheet"
    _inherit = ["mail.thread","mail.activity.mixin"]
    _rec_name = "z_name"
    _order = "id desc"

    z_name = fields.Char(string='Name')
    z_project_id = fields.Many2one('project.project',string='No. Projects',related='z_task_id.project_id',store=True)
    z_task_id = fields.Many2one('project.task',string='No. Tasks')
    z_task_name = fields.Char(string='Name of The Tasks',related='z_task_id.name',store=True)
    z_head_assigned_ids = fields.Many2many('hr.employee',relation='correction_timesheet_head_assigned_ids_rel',string='Head Assigned')
    z_member_assigned_ids = fields.Many2many('hr.employee',relation='correction_timesheet_memeber_assigned_ids_rel',string='Member Assigned')
    z_planned_start_date = fields.Date(string='Planned Start Date')
    z_planned_end_date = fields.Date(string='Planned End Date')
    z_correction_type = fields.Selection([
        ('request','Request'),
        ('change','Change'),
    ],string='Correction Type')
    z_state = fields.Selection([
        ('new', 'Draft'),
        ('waiting_approval', 'Waiting Approval'),
        ('approved', 'Approved'),
        ('cancel', 'Cancelled'),
        ('reject', 'Rejected'),
    ], string='Correction Type')
    z_line_ids = fields.One2many('correction.timesheet.line','z_correction_id',string='Lines')

    @api.model
    def create(self, values):
        sequence = self.env['ir.sequence'].sudo().next_by_code('correction.timesheet.sequence')
        values['z_name'] = sequence
        return super(CorrectionTimesheet, self).create(values)

    def action_confirm(self):
        print('a')

    def action_cancel(self):
        print('a')

    def action_reject(self):
        print('a')

    def action_set_to_draft(self):
        print('a')


class CorrectionTimesheetLine(models.Model):

    _name = "correction.timesheet.line"
    _description = "CR Lines"
    _inherit = ["mail.thread","mail.activity.mixin"]
    _rec_name = "z_name"
    _order = "id asc"

    z_name = fields.Char(string='Description')
    z_correction_id = fields.Many2one('correction.timesheet',string='Correction',ondelete='cascade')
    z_timesheet_id = fields.Many2one('account.analytic.line',string='Timesheet')
    z_ori_start_date = fields.Date(string='Original Start Date')
    z_ori_end_date = fields.Date(string='Original End Date')
    z_current_start_date = fields.Date(string='Current Start Date')
    z_current_end_date = fields.Date(string='Current End Date')
    z_ori_timespent = fields.Float(string='Ori Timespent')
    z_current_timespent = fields.Float(string='Current Timespent')
    z_employee_id = fields.Many2one('hr.employee',string='Employee')
