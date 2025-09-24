from odoo import models, fields, api, _


class AreaRegional(models.Model):

    _name = "area.regional"
    _description = "Area Regional"
    _inherit = ["mail.thread","mail.activity.mixin"]
    _rec_name = "z_name"
    _order = "id desc"

    z_name = fields.Char(string="Area Regional")
