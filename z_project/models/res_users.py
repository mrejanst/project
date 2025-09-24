from odoo import api, fields, models, _


class ResUsers(models.Model):

    _name = "res.users"
    _inherit = ["res.users","mail.thread","mail.activity.mixin"]

    z_project_group_id = fields.Many2one('res.groups',string='Portal Projects')