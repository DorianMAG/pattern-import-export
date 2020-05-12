# Copyright 2020 Akretion France (http://www.akretion.com)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64
from io import BytesIO

import xlsxwriter

from odoo import api, fields, models


class IrExports(models.Model):
    _inherit = "ir.exports"

    pattern_file = fields.Binary(string="Pattern file", readonly=True)
    pattern_last_generation_date = fields.Datetime(
        string="Pattern last generation date", readonly=True
    )

    @api.multi
    def _create_excel_file(self):
        pattern_file = BytesIO()
        book = xlsxwriter.Workbook(pattern_file)
        sheet = book.add_worksheet(self.name)
        bold = book.add_format({"bold": True})
        row = 0
        col = 0
        for export_line in self.export_fields:
            sheet.write(row, col, export_line.name, bold)
            if export_line.is_many2x and export_line.select_tab_id:
                ad_sheet, ad_row = export_line.select_tab_id._generate_additional_sheet(
                    book, bold
                )
                export_line._add_excel_constraint(sheet, col, ad_sheet, ad_row)
            col += 1
        return book, sheet, pattern_file

    @api.multi
    def generate_pattern(self):
        # Allows you to generate an excel file to be used as
        # a template for the import.
        for export in self:
            book, sheet, pattern_file = export._create_excel_file()
            book.close()
            export.pattern_file = base64.b64encode(pattern_file.getvalue())
            export.pattern_last_generation_date = fields.Datetime.now()
        return True

    @api.multi
    def _export_with_record(self, records):
        for export in self:
            book, sheet, pattern_file = export._create_excel_file()
            row = 1
            for record in records:
                col = 0
                for export_line in self.export_fields:
                    value = record[export_line.name]
                    if export_line.is_many2x and export_line.select_tab_id:
                        field_name = export_line.select_tab_id.field_id.name
                        value = record[export_line.name][field_name]
                    sheet.write(row, col, value)
                    col += 1
                row += 1
            book.close()
        return base64.b64encode(pattern_file.getvalue())


class IrExportsLine(models.Model):
    _inherit = "ir.exports.line"

    select_tab_id = fields.Many2one("ir.exports.select.tab", string="Select tab")
    split_nbr = fields.Integer(string="Split nbr")
    is_many2x = fields.Boolean(
        string="Is Many2x field", compute="_compute_is_many2x", store=True
    )
    related_model_id = fields.Many2one(
        "ir.model",
        string="Related model",
        compute="_compute_related_model_id",
        store=True,
    )

    def _get_last_field(self, model, path):
        if "/" not in path:
            path = path + "/"
        field, path = path.split("/", 1)
        if path:
            model = self.env[model]._fields[field]._related_comodel_name
            return self._get_last_field(model, path)
        else:
            return field, model

    @api.multi
    @api.depends("name")
    def _compute_is_many2x(self):
        for export_line in self:
            field, model = export_line._get_last_field(
                export_line.export_id.resource, export_line.name
            )
            if self.env[model]._fields[field].type in ["many2one", "many2many"]:
                export_line.is_many2x = True

    @api.multi
    @api.depends("name")
    def _compute_related_model_id(self):
        for export_line in self:
            field, model = export_line._get_last_field(
                export_line.export_id.resource, export_line.name
            )
            related_comodel = self.env[model]._fields[field]._related_comodel_name
            if related_comodel:
                comodel = self.env["ir.model"].search(
                    [("model", "=", related_comodel)], limit=1
                )
                export_line.related_model_id = comodel.id

    def _add_excel_constraint(self, sheet, col, ad_sheet, ad_row):
        source = "=" + ad_sheet.name + "!$A$2:$A$" + str(ad_row + 100)
        sheet.data_validation(
            1, col, 1048576, col, {"validate": "list", "source": source}
        )
        return True
