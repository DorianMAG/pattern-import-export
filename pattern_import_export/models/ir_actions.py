# Copyright 2020 Akretion France (http://www.akretion.com)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models


class IrActions(models.Model):
    _inherit = "ir.actions.actions"

    @api.model
    def get_bindings(self, model_name):
        """
        Add actions to Import/Export into "more" menu of each object
        @param model_name:
        @return: dict
        """
        res = super().get_bindings(model_name)
        xml_ids = [
            "pattern_import_export.action_export_with_pattern",
            "pattern_import_export.import_pattern_wizard_action",
        ]
        action_list = []
        # the get_bindings method is cached by the orm this meant
        # when we append the action in res["action"] it's added in the dict
        # and as the dict is mutuable the value is cached is updated
        # so we need to be careful to not add it again and again
        if self.env.user.has_group("pattern_import_export.group_pattern_user"):
            for xml_id in xml_ids:
                action = self.env.ref(xml_id).sudo().read()[0]
                action_list.append(action)
            if "action" in res:
                res["action"].extend(action_list)
            else:
                res["action"] = action_list
        return res
