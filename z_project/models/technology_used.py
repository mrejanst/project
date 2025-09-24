from odoo import models, fields, api, _


class TechnologyUsed(models.Model):
    _name = "technology.used"
    _description = "Technology Used"
    _inherit = ["mail.thread","mail.activity.mixin"]
    _rec_name = "z_name"
    _order = "id desc"

    z_name = fields.Char(string="Technology")
