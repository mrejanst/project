from odoo import models, fields, api, _ 


class ProjectProject(models.Model):

    _inherit = ["project.project"]

    @api.depends(
        'z_task_ids.z_actual_start_date',
        'z_task_ids.z_actual_end_date',
        'z_task_ids.timesheet_ids',
        'z_task_ids.z_project_task_state'
    )
    def _getProjectInfo(self):
        for this in self:
            parent_task = self.env['project.task'].sudo().search([('project_id', '=', this.id),('parent_id', '=', False)], order='id asc')
            all_task = self.env['project.task'].sudo().search([('project_id', '=', this.id)], order='id asc')
            actual_start = self.env['project.task'].sudo().search([('project_id', '=', this.id)], order='z_actual_start_date asc', limit=1)
            actual_end = self.env['project.task'].sudo().search([('project_id', '=', this.id)], order='z_actual_end_date desc', limit=1)
            actual_mandays = len(all_task.mapped('timesheet_ids').filtered(lambda x: x.z_timesheet_start_date and x.z_timesheet_end_date))
            this.z_task_ids = [(6, 0, all_task.ids)]
            this.z_actual_start_date = actual_start.z_actual_start_date if actual_start else False
            this.z_actual_end_date = actual_end.z_actual_end_date if actual_end else False
            this.z_actual_budget_mandays = actual_mandays
            progress = (100.0 * len(parent_task.filtered(lambda x: x.z_project_task_state == 'done'))/ len(parent_task)) if parent_task else 0.0
            this.z_progress_project = progress

    @api.onchange('z_group_type_project')
    def onchange_group(self):
        for this in self:
            if this.z_group_type_project == 'non_project':
                this.z_type_in_project = False
            elif this.z_group_type_project == 'project':
                this.z_type_non_project = False

    # override
    name = fields.Char("Project Code", index='trigram', required=True, tracking=True, translate=True,default_export_compatible=True)
    label_tasks = fields.Char(string='Name of The Projects', default=lambda s: s.env._(''), translate=True,help="Name used to refer to the tasks of your project e.g. tasks, tickets, sprints, etc...")
    # added
    z_project_status = fields.Selection([
        ('new', 'Draft'),
        ('waiting', 'Waiting'),
        ('confirm', 'Confirmed'),
        ('sales_dir_to_approve', 'Sales Dir to Approve'),
        ('head_pmo_to_approve', 'Head of PMO to Approve'),
        ('operation', 'Operation'),
        ('budget_approve', 'Budget Approve'),
        ('finance_dir_to_approve', 'Finance Dir to Approve'),
        ('full_approve', 'Fully Approved'),
        ('closed', 'Closed'),
        ('failed', 'Failed'),
    ],string='Project Status',default='new')
    z_project_manager_ids = fields.Many2many('hr.employee',relation='project_project_project_manager_ids_rel',column1='project_project_id',column2='hr_employee_id',string="Project Manager")
    z_group_type_project = fields.Selection([
        ('project', 'Project'),
        ('non_project', 'Non Project')
    ],string='Group')
    z_type_in_project = fields.Selection([
        ('delivery', 'Delivery'),
        ('maintenance', 'Maintenance')
    ],string='Type Of Project')
    z_type_non_project = fields.Selection([
        ('others', 'Others'),
        ('ticket', 'Ticket')
    ],string='Type Of Non Project')
    z_task_ids = fields.Many2many('project.task',relation='project_project_task_ids_rel',string='Task',compute=_getProjectInfo,store=False)
    z_actual_start_date = fields.Date(string='Actual Start Date',compute=_getProjectInfo,store=True)
    z_actual_end_date = fields.Date(string='Actual End Date',compute=_getProjectInfo,store=True)
    z_mandays_budget = fields.Float(string="Budget Mandays")
    z_actual_budget_mandays = fields.Float(string="Actual Mandays",compute=_getProjectInfo,store=True)
    z_value_project = fields.Float(string="Project Value (Rp.)")
    z_progress_project = fields.Float(string="Progress",compute=_getProjectInfo,store=True)
    z_project_teams_ids = fields.Many2many('hr.employee',relation='project_project_project_teams_ids_rel',string='Project Teams')
    z_program_name_ids = fields.One2many('project.project.program.name','z_project_id',string='Program Name')
    z_invoice_plan_ids = fields.One2many('project.project.invoice.plan','z_project_id',string='Invoice Plan')

    def action_confirm(self):
        if self.z_project_status == 'new':
            self.z_project_status = 'waiting'
        elif self.z_project_status == 'waiting':
            self.z_project_status = 'confirm'
        elif self.z_project_status == 'confirm':
            self.z_project_status = 'sales_dir_to_approve'
        elif self.z_project_status == 'sales_dir_to_approve':
            self.z_project_status = 'head_pmo_to_approve'
        elif self.z_project_status == 'head_pmo_to_approve':
            self.z_project_status = 'operation'
        elif self.z_project_status == 'operation':
            self.z_project_status = 'budget_approve'
        elif self.z_project_status == 'budget_approve':
            self.z_project_status = 'finance_dir_to_approve'
        elif self.z_project_status == 'finance_dir_to_approve':
            self.z_project_status = 'full_approve'
        elif self.z_project_status == 'full_approve':
            self.z_project_status = 'closed'

    def action_failed(self):
        self.z_project_status = 'failed'

    def action_set_to_draft(self):
        self.z_project_status = 'new'

    def action_view_tasks(self):
        return {
            "name": _("Tasks"),
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "view_mode": "list,form",
            "domain": [('id', 'in', self.task_ids.ids)],
            "context": {},
            'views': [
                [self.env.ref('z_project.z_project_task_list').id, 'list'],
                [self.env.ref('z_project.z_project_task_form_inherit_project').id, 'form'],
            ],
        }


class ProjectProjectProgramName(models.Model):

    _name = "project.project.program.name"
    _description = "Program Name"
    _inherit = ["mail.thread","mail.activity.mixin"]
    _rec_name = "z_name"
    _order = "id asc"

    z_project_id = fields.Many2one('project.project',string='Project',ondelete='cascade')
    z_name = fields.Char(string='Pogram Name')


class ProjectProjectInvoicePlan(models.Model):

    _name = "project.project.invoice.plan"
    _description = "Invoice Plan"
    _inherit = ["mail.thread","mail.activity.mixin"]
    _rec_name = "z_name"
    _order = "id asc"

    z_project_id = fields.Many2one('project.project',string='Project',ondelete='cascade')
    z_name = fields.Char(string='No. Invoice')
    z_description = fields.Char(string='Invoice Description')
    z_date = fields.Date(string='Invoice Date')
    z_amount_total = fields.Float(string='Amount Total')
    z_state = fields.Char(string='Status')
