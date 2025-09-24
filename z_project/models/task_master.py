from odoo import models, fields, api, _


class TaskMaster(models.Model):

    _name = "task.master"
    _description = "Task Master"
    _inherit = ["mail.thread","mail.activity.mixin"]
    _rec_name = "z_name"
    _order = "id desc"

    @api.depends('z_name', 'z_parent_id.z_complete_name')
    def _getCompleteName(self):
        for this in self:
            if this.z_parent_id:
                this.z_complete_name = '%s / %s' % (this.z_parent_id.z_complete_name, this.z_name)
            else:
                this.z_complete_name = this.z_name

    z_name = fields.Char(string="Master Task")
    z_parent_id = fields.Many2one('task.master',string="Parent Task")
    z_complete_name = fields.Char('Complete Name',compute=_getCompleteName,recursive=True,store=True)
