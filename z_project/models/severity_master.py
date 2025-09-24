from odoo import models, fields, api


class SeverityMaster(models.Model):

    _name = "severity.master"
    _description = "Severity Master"
    _inherit = ["mail.thread","mail.activity.mixin"]
    _rec_name = "z_name"
    _order = "id desc"

    z_name = fields.Char(string="Severity")
